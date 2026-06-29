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
from models.corbeille import Corbeille
from models.presentation import Presentation

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
    "Corbeille",
    "Presentation",
]
