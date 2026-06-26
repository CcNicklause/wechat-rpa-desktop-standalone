import random
import time
import uuid
from datetime import datetime, timezone

from backend.app.core.audit import AuditLogger
from backend.app.core.config import Settings
from backend.app.core.errors import AppError, not_found
from backend.app.core.rate_limit import enforce_daily_limit, increment_daily_count, runtime_guard
from backend.app.core.security import mask_phone
from backend.app.schemas.lead import LeadStatus
from backend.app.schemas.rpa import CheckItem
from backend.app.services.consent_service import assert_lead_has_consent
from backend.app.services.simulation_rpa import execute_simulation
from backend.app.services.wechat_rpa import RpaBusinessOutcome, execute_single_add_request
from backend.app.storage.sqlite_store import SQLiteStore
from backend.app.workers.local_queue import run_background


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RpaOrchestrator:
    def __init__(self, store: SQLiteStore, audit: AuditLogger, settings: Settings):
        self.store = store
        self.audit = audit
        self.settings = settings

    def precheck(self, lead_id: str) -> dict:
        lead = self._require_lead(lead_id)
        self.audit.record(
            'rpa.precheck.started',
            actor_id=lead['sales_id'],
            lead_id=lead_id,
            phone_masked=mask_phone(lead['phone']),
            rpa_mode=self.settings.rpa_mode,
            customer_consent=bool(lead.get('customer_consent')),
            result='started',
        )

        checks = [
            CheckItem(
                name='customer_consent',
                passed=bool(lead.get('customer_consent')),
                message='客户已明确同意' if lead.get('customer_consent') else '缺少客户明确同意',
            ),
            CheckItem(
                name='sales_confirmed_call',
                passed=bool(lead.get('sales_confirmed_call')),
                message='销售已确认本次通话' if lead.get('sales_confirmed_call') else '销售未确认本次通话',
            ),
            CheckItem(
                name='consent_evidence',
                passed=bool((lead.get('consent_evidence') or '').strip()),
                message='已记录同意证据' if (lead.get('consent_evidence') or '').strip() else '缺少同意证据',
            ),
            CheckItem(
                name='single_target_only',
                passed=True,
                message='本接口仅支持单个线索',
            ),
            CheckItem(
                name='daily_circuit_breaker',
                passed=self.store.get_daily_count(lead['sales_id'], datetime.now().date().isoformat()) < self.settings.rpa_daily_limit,
                message=f"今日真实 RPA 上限 {self.settings.rpa_daily_limit} 次",
            ),
            CheckItem(
                name='rpa_mode',
                passed=True,
                message=f'当前模式: {self.settings.rpa_mode}',
            ),
        ]
        allowed = all(item.passed for item in checks)
        self.audit.record(
            'rpa.precheck.passed' if allowed else 'rpa.precheck.failed',
            actor_id=lead['sales_id'],
            lead_id=lead_id,
            phone_masked=mask_phone(lead['phone']),
            rpa_mode=self.settings.rpa_mode,
            customer_consent=bool(lead.get('customer_consent')),
            result='success' if allowed else 'failed',
        )
        return {
            'allowed': allowed,
            'rpa_mode': self.settings.rpa_mode,
            'dry_run_default': True,
            'checks': checks,
        }

    def add_wechat(self, lead_id: str, greeting: str, dry_run: bool, human_approval: bool) -> dict:
        lead = self._require_lead(lead_id)
        self._validate_add_request(lead, dry_run, human_approval)

        effective_mode = 'simulation' if dry_run or self.settings.rpa_mode == 'simulation' else 'real'
        timestamp = now_iso()
        job = {
            'job_id': f'job_{uuid.uuid4().hex[:12]}',
            'lead_id': lead_id,
            'status': 'SIMULATION_QUEUED' if effective_mode == 'simulation' else 'REAL_QUEUED',
            'rpa_mode': effective_mode,
            'dry_run': effective_mode == 'simulation',
            'human_approval': human_approval,
            'greeting': greeting,
            'steps': [],
            'created_at': timestamp,
            'updated_at': timestamp,
        }
        self.store.create_job(job)
        self.audit.record(
            'rpa.simulation.started' if effective_mode == 'simulation' else 'rpa.real.requested',
            actor_id=lead['sales_id'],
            lead_id=lead_id,
            phone_masked=mask_phone(lead['phone']),
            rpa_mode=effective_mode,
            dry_run=job['dry_run'],
            customer_consent=bool(lead.get('customer_consent')),
            human_approval=human_approval,
            result='queued',
        )
        run_background(lambda: self._run_job(job['job_id']))
        return {
            'job_id': job['job_id'],
            'status': job['status'],
            'message': '已进入模拟执行队列，未触发真实微信操作' if effective_mode == 'simulation' else '已进入真实 RPA 队列，请保持微信客户端可见',
        }

    def get_job(self, job_id: str) -> dict:
        job = self.store.get_job(job_id)
        if not job:
            raise not_found('RPA 任务不存在')
        return job

    def _run_job(self, job_id: str) -> None:
        job = self.store.get_job(job_id)
        if not job:
            return
        lead = self._require_lead(job['lead_id'])
        steps = list(job.get('steps', []))

        def update_step(step: str) -> None:
            steps.append(step)
            self.store.update_job(job_id, steps=steps, updated_at=now_iso())

        max_retries = 1
        for attempt in range(max_retries + 1):
            try:
                with runtime_guard.single_task():
                    if job['rpa_mode'] == 'simulation':
                        self.store.update_job(job_id, status='SIMULATION_RUNNING', updated_at=now_iso())
                        execute_simulation(update_step)
                        self.store.update_job(job_id, status='SIMULATION_COMPLETED', steps=steps, updated_at=now_iso())
                        self.store.update_lead(lead['lead_id'], status=LeadStatus.RPA_SIMULATED.value, updated_at=now_iso())
                        self.audit.record(
                            'rpa.simulation.completed',
                            actor_id=lead['sales_id'],
                            lead_id=lead['lead_id'],
                            phone_masked=mask_phone(lead['phone']),
                            rpa_mode='simulation',
                            dry_run=True,
                            customer_consent=bool(lead.get('customer_consent')),
                            human_approval=bool(job.get('human_approval')),
                            result='success',
                        )
                        return

                    self.store.update_job(job_id, status='REAL_RUNNING', updated_at=now_iso())
                    self.store.update_lead(lead['lead_id'], status=LeadStatus.RPA_EXECUTING.value, updated_at=now_iso())
                    if attempt == 0:
                        self.audit.record(
                            'rpa.real.approved',
                            actor_id=lead['sales_id'],
                            lead_id=lead['lead_id'],
                            phone_masked=mask_phone(lead['phone']),
                            rpa_mode='real',
                            dry_run=False,
                            customer_consent=bool(lead.get('customer_consent')),
                            human_approval=True,
                            result='approved',
                        )
                    delay = random.uniform(self.settings.rpa_min_interval_seconds, self.settings.rpa_max_interval_seconds)
                    update_step(f'safety_delay: 真实 RPA 执行前安全等待 {delay:.1f} 秒')
                    time.sleep(delay)
                    if attempt == 0:
                        self.audit.record(
                            'rpa.real.started',
                            actor_id=lead['sales_id'],
                            lead_id=lead['lead_id'],
                            phone_masked=mask_phone(lead['phone']),
                            rpa_mode='real',
                            dry_run=False,
                            customer_consent=True,
                            human_approval=True,
                            result='started',
                        )
                    self._run_add_request_with_timeout(lead['phone'], job['greeting'], update_step, job_id)
                    increment_daily_count(self.store, lead['sales_id'])
                    lead_status = (
                        LeadStatus.WECHAT_ACCEPTED
                        if self._steps_indicate_direct_acceptance(steps)
                        else LeadStatus.WECHAT_ADD_REQUESTED
                    )
                    self.store.update_job(
                        job_id,
                        status='REAL_COMPLETED',
                        steps=steps,
                        outcome_type='success',
                        updated_at=now_iso(),
                    )
                    self.store.update_lead(lead['lead_id'], status=lead_status.value, updated_at=now_iso())
                    self.audit.record(
                        'rpa.real.completed',
                        actor_id=lead['sales_id'],
                        lead_id=lead['lead_id'],
                        phone_masked=mask_phone(lead['phone']),
                        rpa_mode='real',
                        dry_run=False,
                        customer_consent=True,
                        human_approval=True,
                        result='success',
                    )
                    self._record_wechat_success_outcome(lead, lead_status)
                    return
            except RpaBusinessOutcome as outcome:
                # 业务终态（搜不到、风控、已经是好友）绝不重试，直接抛出记录
                self._finalize_business_outcome(job_id, lead, steps, outcome)
                return
            except Exception as exc:
                is_app_error = isinstance(exc, AppError)
                code = exc.detail['code'] if is_app_error and isinstance(exc.detail, dict) else 'SYS_RPA_FAILED'
                message = exc.detail['message'] if is_app_error and isinstance(exc.detail, dict) else str(exc)
                
                if attempt < max_retries:
                    update_step(f"SYS_ERROR_RETRY: 发生系统异常 [{code}] {message}，触发自动重试机制 ({attempt+1}/{max_retries})...")
                    time.sleep(2.0)
                    continue
                
                self._fail_job(job_id, lead, steps, code, message)
                return

    def _run_add_request_with_timeout(
        self, phone: str, greeting: str, update_step, job_id: str
    ) -> None:
        """在独立线程跑加微链路，主线程 join 超时则判 SYS_RPA_TIMEOUT（O-1）。

        线程内的异常（含 RpaBusinessOutcome / AppError）通过容器回传，
        在主线程重新抛出，以便 _run_job 的 except 链统一处理。
        """
        import threading

        result: dict = {'exc': None}
        cancel_token = threading.Event()

        def _worker() -> None:
            # COM/uiautomation 是线程绑定的：在这个新线程里必须先初始化 COM
            # 套间，否则 uiautomation 调用会抛 E_FAIL (0x80004005)。
            com_inited = False
            try:
                import comtypes

                comtypes.CoInitializeEx(comtypes.COINIT_APARTMENTTHREADED)
                com_inited = True
            except Exception:
                # 非 Windows / comtypes 不可用时跳过；execute 内部会自行报错
                pass
            try:
                execute_single_add_request(phone, greeting, update_step, job_id=job_id, cancel_token=cancel_token)
            except BaseException as exc:  # 回传任何异常到主线程
                result['exc'] = exc
            finally:
                if com_inited:
                    try:
                        import comtypes

                        comtypes.CoUninitialize()
                    except Exception:
                        pass

        worker = threading.Thread(target=_worker, daemon=True)
        worker.start()
        worker.join(timeout=self.settings.rpa_task_timeout_seconds)

        if worker.is_alive():
            # 线程仍在跑：标记超时。虽然无法安全强杀，但通过 cancel_token 通知线程内部安全退出，
            # 避免它在后台继续盲点盲点（幽灵操作）污染下一次任务。
            cancel_token.set()
            raise AppError(
                'SYS_RPA_TIMEOUT',
                f'加微任务超过 {self.settings.rpa_task_timeout_seconds}s 未完成，已判定超时',
            )
        if result['exc'] is not None:
            raise result['exc']

    @staticmethod
    def _steps_indicate_direct_acceptance(steps: list[str]) -> bool:
        return any(step.startswith('ADD_DIRECTLY_CONFIRMED') for step in steps)

    def _record_wechat_success_outcome(self, lead: dict, lead_status: LeadStatus) -> None:
        if lead_status == LeadStatus.WECHAT_ACCEPTED:
            self.audit.record(
                'wechat.friend.accepted',
                actor_id=lead['sales_id'],
                lead_id=lead['lead_id'],
                phone_masked=mask_phone(lead['phone']),
                rpa_mode='real',
                result='accepted',
                reason_code='DIRECT_CONFIRM',
                message='真实 RPA 已确认通过朋友验证，当前已成为好友',
            )
            return

        self.audit.record(
            'wechat.friend.requested',
            actor_id=lead['sales_id'],
            lead_id=lead['lead_id'],
            phone_masked=mask_phone(lead['phone']),
            rpa_mode='real',
            result='pending',
            reason_code='REQUEST_SENT',
            message='真实 RPA 已发送好友申请，等待对方通过',
        )

    # 业务终态码 → LeadStatus
    _OUTCOME_LEAD_STATUS = {
        'BIZ_TARGET_NOT_FOUND': LeadStatus.WECHAT_TARGET_NOT_FOUND,
        'BIZ_ALREADY_FRIEND': LeadStatus.WECHAT_ALREADY_FRIEND,
        'BIZ_ADD_REJECTED': LeadStatus.WECHAT_ADD_REJECTED,
        'BIZ_RISK_CONTROL': LeadStatus.WECHAT_RISK_CONTROL,
    }

    def _finalize_business_outcome(
        self, job_id: str, lead: dict, steps: list[str], outcome: RpaBusinessOutcome
    ) -> None:
        """业务终态收尾：独立 job status + lead 状态，不进 _fail_job、不告警。"""
        lead_status = self._OUTCOME_LEAD_STATUS.get(outcome.code, LeadStatus.RPA_FAILED)
        self.store.update_job(
            job_id,
            status=f'REAL_{outcome.code}',
            steps=steps,
            error_code=outcome.code,
            error_message=outcome.message,
            outcome_type='business',
            updated_at=now_iso(),
        )
        self.store.update_lead(lead['lead_id'], status=lead_status.value, updated_at=now_iso())

        # 风控终态触发当天熔断：把今日计数顶到上限，阻止后续任务
        if outcome.circuit_break:
            try:
                for _ in range(self.settings.rpa_daily_limit):
                    increment_daily_count(self.store, lead['sales_id'])
            except Exception:
                pass

        self.audit.record(
            'rpa.real.business_outcome',
            actor_id=lead['sales_id'],
            lead_id=lead['lead_id'],
            phone_masked=mask_phone(lead['phone']),
            rpa_mode='real',
            dry_run=False,
            customer_consent=True,
            human_approval=True,
            result='business_outcome',
            reason_code=outcome.code,
            message=outcome.message,
        )

    def _fail_job(self, job_id: str, lead: dict, steps: list[str], code: str, message: str) -> None:
        self.store.update_job(
            job_id,
            status='FAILED',
            steps=steps,
            error_code=code,
            error_message=message,
            outcome_type='system',
            updated_at=now_iso(),
        )
        self.store.update_lead(lead['lead_id'], status=LeadStatus.RPA_FAILED.value, updated_at=now_iso())
        self.audit.record(
            'rpa.real.failed',
            actor_id=lead['sales_id'],
            lead_id=lead['lead_id'],
            phone_masked=mask_phone(lead['phone']),
            rpa_mode='real',
            result='failed',
            reason_code=code,
            message=message,
        )

    def _validate_add_request(self, lead: dict, dry_run: bool, human_approval: bool) -> None:
        try:
            assert_lead_has_consent(lead)
        except AppError:
            self.audit.record(
                'rpa.blocked.no_consent',
                actor_id=lead['sales_id'],
                lead_id=lead['lead_id'],
                phone_masked=mask_phone(lead['phone']),
                rpa_mode=self.settings.rpa_mode,
                dry_run=dry_run,
                customer_consent=bool(lead.get('customer_consent')),
                human_approval=human_approval,
                result='blocked',
                reason_code='CONSENT_REQUIRED',
            )
            raise

        if not dry_run and self.settings.rpa_mode != 'real':
            self.audit.record(
                'rpa.blocked.dry_run_default',
                actor_id=lead['sales_id'],
                lead_id=lead['lead_id'],
                phone_masked=mask_phone(lead['phone']),
                rpa_mode=self.settings.rpa_mode,
                dry_run=dry_run,
                customer_consent=True,
                human_approval=human_approval,
                result='blocked',
                reason_code='REAL_RPA_DISABLED',
                message='当前为模拟模式，未触发真实微信操作',
            )
            raise AppError('REAL_RPA_DISABLED', '当前为模拟模式，未触发真实微信操作')

        if self.settings.rpa_mode == 'real' and not dry_run:
            try:
                enforce_daily_limit(self.store, self.settings, lead['sales_id'])
            except AppError:
                self.audit.record(
                    'rpa.blocked.circuit_breaker',
                    actor_id=lead['sales_id'],
                    lead_id=lead['lead_id'],
                    phone_masked=mask_phone(lead['phone']),
                    rpa_mode='real',
                    dry_run=False,
                    customer_consent=True,
                    human_approval=human_approval,
                    result='blocked',
                    reason_code='DAILY_CIRCUIT_BREAKER_OPEN',
                )
                raise

    def _require_lead(self, lead_id: str) -> dict:
        lead = self.store.get_lead(lead_id)
        if not lead:
            raise not_found('线索不存在')
        return lead
