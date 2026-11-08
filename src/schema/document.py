from enum import Enum

from pydantic import BaseModel


class DocumentKind(str, Enum):
    PDF = "pdf"
    IMAGE = "image"


class Document(BaseModel):
    id: int
    filename: str
    kind: DocumentKind
    path: str
    created_at: str
