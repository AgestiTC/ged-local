"""Modèles SQLAlchemy — DocFlow AI"""

from models.document import Base, Document
from models.embedding import Embedding
from models.job import Job
from models.metadata import MetadonneeIA
from models.template import Template
from models.version import Version
from models.prompt import PromptPreset
from models.folder import DossierSurveille
from models.config import Config
from models.source import Source
from models.rapport import Rapport
from models.audit import AuditEvent
from models.corbeille import Corbeille
from models.presentation import Presentation
from models.model_meta import ModelMeta
from models.reorg import ReorgMove, ReorgPlan
from models.document_link import DocumentLink
from models.publieur import ProjetPublieur
from models.publication import Publication

__all__ = [
    "Base",
    "Document",
    "Embedding",
    "Job",
    "MetadonneeIA",
    "Template",
    "Version",
    "PromptPreset",
    "DossierSurveille",
    "Config",
    "Source",
    "Rapport",
    "AuditEvent",
    "Corbeille",
    "Presentation",
    "ModelMeta",
    "ReorgPlan",
    "ReorgMove",
    "DocumentLink",
    "ProjetPublieur",
    "Publication",
]
