from dependency_injector import containers, providers

from apps.cvs.repositories.cv_repository import CvRepository
from apps.cvs.services.cv_service import CvService


class CvsContainer(containers.DeclarativeContainer):
    cv_repository = providers.Singleton(CvRepository)
    cv_service = providers.Singleton(CvService, cv_repo=cv_repository)
