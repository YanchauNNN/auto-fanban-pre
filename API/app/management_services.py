from __future__ import annotations

from dataclasses import dataclass

from src.accounts.account_csv_store import AccountCsvStore
from src.accounts.account_registry import AccountRegistry
from src.accounts.personnel_normalizer import PersonnelNormalizer
from src.archive.admin_config_store import AdminConfigStore
from src.archive.overwrite_service import ArchiveOverwriteService
from src.archive.retry_worker import ArchiveRetryWorker
from src.archive.service import ArchiveService
from src.auth.password_service import PasswordService
from src.auth.session_service import SessionService
from src.task_groups.serializers import TaskGroupSerializers
from src.task_groups.service import TaskGroupService
from src.task_groups.visibility import TaskGroupVisibility
from src.workflow.assignee_resolver import WorkflowAssigneeResolver
from src.workflow.input_validator import WorkflowInputValidator
from src.workflow.service import WorkflowService
from src.workflow.visibility import WorkflowVisibility
from src.workload.calculator import WorkloadCalculator
from src.workload.queries import WorkloadQueries
from src.workload.settlement_service import WorkloadSettlementService


@dataclass
class ManagementServices:
    account_store: AccountCsvStore
    account_registry: AccountRegistry
    personnel_normalizer: PersonnelNormalizer
    session_service: SessionService
    password_service: PasswordService
    workflow_validator: WorkflowInputValidator
    workflow_service: WorkflowService
    admin_config_store: AdminConfigStore
    archive_service: ArchiveService
    archive_retry_worker: ArchiveRetryWorker
    workload_calculator: WorkloadCalculator
    workload_settlement_service: WorkloadSettlementService
    workload_queries: WorkloadQueries
    task_group_service: TaskGroupService

    @classmethod
    def build(cls, runtime) -> "ManagementServices":
        account_store = AccountCsvStore()
        account_registry = AccountRegistry(account_store)
        personnel_normalizer = PersonnelNormalizer(account_registry)
        session_service = SessionService(account_registry)
        password_service = PasswordService(account_registry)
        workflow_validator = WorkflowInputValidator()
        workflow_service = WorkflowService(WorkflowAssigneeResolver())
        admin_config_store = AdminConfigStore(runtime.config)
        overwrite_service = ArchiveOverwriteService(runtime.group_manager, runtime.job_manager)
        archive_service = ArchiveService(
            group_manager=runtime.group_manager,
            job_manager=runtime.job_manager,
            shared_prep_service=runtime.shared_prep_service,
            admin_config_store=admin_config_store,
            overwrite_service=overwrite_service,
        )
        archive_retry_worker = ArchiveRetryWorker(
            archive_service=archive_service,
            group_manager=runtime.group_manager,
            config=runtime.config,
        )
        workload_calculator = WorkloadCalculator()
        workload_settlement_service = WorkloadSettlementService(workload_calculator)
        workload_queries = WorkloadQueries()
        task_group_service = TaskGroupService(
            group_manager=runtime.group_manager,
            job_manager=runtime.job_manager,
            shared_prep_service=runtime.shared_prep_service,
            account_registry=account_registry,
            personnel_normalizer=personnel_normalizer,
            workflow_validator=workflow_validator,
            workflow_service=workflow_service,
            task_group_visibility=TaskGroupVisibility(),
            workflow_visibility=WorkflowVisibility(),
            serializers=TaskGroupSerializers(),
            workload_calculator=workload_calculator,
            workload_settlement_service=workload_settlement_service,
            workload_queries=workload_queries,
            archive_service=archive_service,
        )
        return cls(
            account_store=account_store,
            account_registry=account_registry,
            personnel_normalizer=personnel_normalizer,
            session_service=session_service,
            password_service=password_service,
            workflow_validator=workflow_validator,
            workflow_service=workflow_service,
            admin_config_store=admin_config_store,
            archive_service=archive_service,
            archive_retry_worker=archive_retry_worker,
            workload_calculator=workload_calculator,
            workload_settlement_service=workload_settlement_service,
            workload_queries=workload_queries,
            task_group_service=task_group_service,
        )

    def start(self) -> None:
        self.archive_retry_worker.start()

    def stop(self) -> None:
        self.archive_retry_worker.stop()
