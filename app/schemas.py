from pydantic import BaseModel, Field
from typing import List, Optional, Any
from datetime import datetime


class Link(BaseModel):
    rel: str
    href: str
    method: Optional[str] = "GET"
    type: Optional[str] = None


class ValueConstraintsBase(BaseModel):
    dataType: str = Field(..., pattern="^(string|number|boolean)$")
    format: Optional[str] = Field(None, pattern="^(date|datetime|url|decimal|integer)$")
    required: Optional[bool] = False
    readOnly: Optional[bool] = False
    multiple: Optional[bool] = False
    range: Optional[bool] = False
    enum: Optional[List[Any]] = None


class ValueConstraintsCreate(ValueConstraintsBase):
    pass


class ValueConstraintsUpdate(BaseModel):
    dataType: Optional[str] = Field(None, pattern="^(string|number|boolean)$")
    format: Optional[str] = Field(None, pattern="^(date|datetime|url|decimal|integer)$")
    required: Optional[bool] = None
    readOnly: Optional[bool] = None
    multiple: Optional[bool] = None
    range: Optional[bool] = None
    enum: Optional[List[Any]] = None


class ValueConstraintsResponse(ValueConstraintsBase):
    id: int

    class Config:
        from_attributes = True


class AttributeBase(BaseModel):
    name: str
    defaultValue: Optional[str] = None
    valueConstraints: Optional[ValueConstraintsBase] = None


class AttributeCreate(AttributeBase):
    valueConstraints: Optional[ValueConstraintsCreate] = None


class AttributeUpdate(BaseModel):
    name: Optional[str] = None
    defaultValue: Optional[str] = None
    valueConstraints: Optional[ValueConstraintsUpdate] = None


class AttributeResponse(BaseModel):
    id: int
    name: str
    defaultValue: Optional[str] = None
    valueConstraints: Optional[ValueConstraintsResponse] = None

    class Config:
        from_attributes = True


class TreatmentDefinitionBase(BaseModel):
    name: str
    description: Optional[str] = None


class TreatmentDefinitionCreate(TreatmentDefinitionBase):
    attributes: Optional[List[AttributeCreate]] = None


class TreatmentDefinitionUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    attributes: Optional[List[AttributeCreate]] = None


class TreatmentDefinitionSummary(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    createdBy: Optional[str] = None
    creationTimeStamp: Optional[datetime] = None
    modifiedBy: Optional[str] = None
    modifiedTimeStamp: Optional[datetime] = None
    majorRevision: int = 1
    minorRevision: int = 0
    checkout: bool = False
    locked: bool = False
    status: str = "valid"
    links: List[Link] = []

    class Config:
        from_attributes = True


class TreatmentDefinitionResponse(TreatmentDefinitionSummary):
    attributes: List[AttributeResponse] = []
    folderType: Optional[str] = None
    sourceRevisionUri: Optional[str] = None
    copyTimeStamp: Optional[datetime] = None
    version: int = 1


class TreatmentDefinitionRevisionSummary(BaseModel):
    id: int
    name: str
    majorRevision: int
    minorRevision: int
    status: str
    links: List[Link] = []


class CollectionResponse(BaseModel):
    items: List[Any]
    start: int = 0
    limit: int = 10
    count: int = 0
    links: List[Link] = []


class TreatmentDefinitionRoot(BaseModel):
    links: List[Link] = Field(..., description="HATEOAS links")

    class Config:
        json_schema_extra = {
            "example": {
                "links": [
                    {"rel": "treatmentDefinitions", "href": "/treatmentDefinition/definitions", "method": "GET"},
                    {"rel": "createTreatmentDefinition", "href": "/treatmentDefinition/definitions", "method": "POST"},
                ]
            }
        }


class RevisionCreate(BaseModel):
    revisionType: Optional[str] = Field("minor", pattern="^(major|minor)$")
    fromRevisionUri: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None


class RevisionSelection(BaseModel):
    type: str = Field("id", pattern="^id$")
    resources: List[int]


class RevisionBatchQuery(BaseModel):
    selection: RevisionSelection
