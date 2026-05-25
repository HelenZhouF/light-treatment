from pydantic import BaseModel, Field, field_validator
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


# ------------------------- Treatment Definition Group schemas -------------------------


class AttributeValueMappingCreate(BaseModel):
    attributeId: Optional[int] = None
    attributeName: str
    mappingType: str = Field(..., pattern="^(variable|constant)$")
    value: Optional[str] = None


class AttributeValueMappingUpdate(BaseModel):
    attributeId: Optional[int] = None
    attributeName: Optional[str] = None
    mappingType: Optional[str] = Field(None, pattern="^(variable|constant)$")
    value: Optional[str] = None


class AttributeValueMappingResponse(BaseModel):
    id: int
    attributeId: Optional[int] = None
    attributeName: str
    mappingType: str
    value: Optional[str] = None

    class Config:
        from_attributes = True


class AttributeNameAliasCreate(BaseModel):
    attributeId: Optional[int] = None
    attributeName: str
    aliasName: str


class AttributeNameAliasUpdate(BaseModel):
    attributeId: Optional[int] = None
    attributeName: Optional[str] = None
    aliasName: Optional[str] = None


class AttributeNameAliasResponse(BaseModel):
    id: int
    attributeId: Optional[int] = None
    attributeName: str
    aliasName: str

    class Config:
        from_attributes = True


class GroupMemberCreate(BaseModel):
    definitionId: int
    definitionRevisionId: Optional[int] = None
    definitionRevisionName: Optional[str] = None
    attributeValueMappings: Optional[List[AttributeValueMappingCreate]] = None
    attributeNameAliases: Optional[List[AttributeNameAliasCreate]] = None


class GroupMemberUpdate(BaseModel):
    definitionId: Optional[int] = None
    definitionRevisionId: Optional[int] = None
    definitionRevisionName: Optional[str] = None
    attributeValueMappings: Optional[List[AttributeValueMappingCreate]] = None
    attributeNameAliases: Optional[List[AttributeNameAliasCreate]] = None


class GroupMemberResponse(BaseModel):
    id: int
    definitionId: int
    definitionRevisionId: Optional[int] = None
    definitionRevisionName: Optional[str] = None
    attributeValueMappings: List[AttributeValueMappingResponse] = []
    attributeNameAliases: List[AttributeNameAliasResponse] = []

    class Config:
        from_attributes = True


class TreatmentDefinitionGroupBase(BaseModel):
    name: str = Field(..., min_length=1)
    description: Optional[str] = None

    @field_validator("name")
    @classmethod
    def validate_name_not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("name must not be empty or blank")
        return v.strip()


class TreatmentDefinitionGroupCreate(TreatmentDefinitionGroupBase):
    parentFolderUri: Optional[str] = None
    fromRevisionUri: Optional[str] = None
    members: Optional[List[GroupMemberCreate]] = None


class TreatmentDefinitionGroupUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1)
    description: Optional[str] = None
    members: Optional[List[GroupMemberCreate]] = None

    @field_validator("name")
    @classmethod
    def validate_name_not_blank(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and (not v or not v.strip()):
            raise ValueError("name must not be empty or blank")
        return v.strip() if v is not None else None


class TreatmentDefinitionGroupSummary(BaseModel):
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
    activationStatus: Optional[str] = None
    activationError: Optional[str] = None
    activatedTimeStamp: Optional[datetime] = None
    parentFolderUri: Optional[str] = None
    fromRevisionUri: Optional[str] = None
    links: List[Link] = []

    class Config:
        from_attributes = True


class TreatmentDefinitionGroupRevisionSummary(BaseModel):
    id: int
    name: str
    majorRevision: int
    minorRevision: int
    status: str
    activationStatus: Optional[str] = None
    links: List[Link] = []


class TreatmentDefinitionGroupResponse(TreatmentDefinitionGroupSummary):
    members: List[GroupMemberResponse] = []
    version: int = 1


# ------------------------- Treatment Definition Group Revision schemas -------------------------


class GroupRevisionAttributeValueMappingCreate(BaseModel):
    attributeId: Optional[int] = None
    attributeName: str
    mappingType: str = Field(..., pattern="^(variable|constant)$")
    value: Optional[str] = None


class GroupRevisionAttributeNameAliasCreate(BaseModel):
    attributeId: Optional[int] = None
    attributeName: str
    aliasName: str


class GroupRevisionMemberCreate(BaseModel):
    definitionId: int
    definitionRevisionId: Optional[int] = None
    definitionRevisionName: Optional[str] = None
    attributeValueMappings: Optional[List[GroupRevisionAttributeValueMappingCreate]] = None
    attributeNameAliases: Optional[List[GroupRevisionAttributeNameAliasCreate]] = None


class GroupRevisionCreate(BaseModel):
    revisionType: Optional[str] = Field("minor", pattern="^(major|minor)$")
    fromRevisionUri: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    members: Optional[List[GroupRevisionMemberCreate]] = None


class GroupRevisionActivateRequest(BaseModel):
    id: Optional[int] = None
    uri: Optional[str] = None
