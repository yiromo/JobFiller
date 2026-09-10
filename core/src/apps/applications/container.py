from dependency_injector import containers, providers

from apps.applications.repositories.application_repository import ApplicationRepository
from apps.applications.services.application_service import ApplicationService
from apps.cvs.container import CvsContainer


class ApplicationsContainer(containers.DeclarativeContainer):
    application_repository = providers.Singleton(ApplicationRepository)
    application_service = providers.Singleton(
        ApplicationService,
        application_repo=application_repository,
        cv_repo=CvsContainer.cv_repository,
    )
