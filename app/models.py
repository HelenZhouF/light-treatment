from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, Float
from sqlalchemy.orm import relationship
from datetime import datetime

from app.database import Base


class TreatmentDefinition(Base):
    __tablename__ = "treatment_definitions"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)

    createdBy = Column(String(255), nullable=True)
    creationTimeStamp = Column(DateTime, default=datetime.utcnow)
    modifiedBy = Column(String(255), nullable=True)
    modifiedTimeStamp = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    majorRevision = Column(Integer, default=1)
    minorRevision = Column(Integer, default=0)
    checkout = Column(Boolean, default=False)
    locked = Column(Boolean, default=False)
    status = Column(String(50), default="valid")
    folderType = Column(String(255), nullable=True)
    sourceRevisionUri = Column(Text, nullable=True)
    copyTimeStamp = Column(DateTime, nullable=True)

    version = Column(Integer, default=1)

    attributes = relationship("Attribute", back_populates="treatment_definition", cascade="all, delete-orphan")
    revisions = relationship("TreatmentDefinitionRevision", back_populates="definition", cascade="all, delete-orphan")


class TreatmentDefinitionRevision(Base):
    __tablename__ = "treatment_definition_revisions"

    id = Column(Integer, primary_key=True, index=True)
    treatment_definition_id = Column(Integer, ForeignKey("treatment_definitions.id"), nullable=False, index=True)

    name = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)

    createdBy = Column(String(255), nullable=True)
    creationTimeStamp = Column(DateTime, default=datetime.utcnow)
    modifiedBy = Column(String(255), nullable=True)
    modifiedTimeStamp = Column(DateTime, default=datetime.utcnow)

    majorRevision = Column(Integer, default=1)
    minorRevision = Column(Integer, default=0)
    checkout = Column(Boolean, default=False)
    locked = Column(Boolean, default=False)
    status = Column(String(50), default="valid")
    folderType = Column(String(255), nullable=True)
    sourceRevisionUri = Column(Text, nullable=True)
    copyTimeStamp = Column(DateTime, nullable=True)

    fromRevisionUri = Column(Text, nullable=True)
    isActive = Column(Boolean, default=False)

    definition = relationship("TreatmentDefinition", back_populates="revisions")
    attributes = relationship("RevisionAttribute", back_populates="revision", cascade="all, delete-orphan")
    checkOuts = relationship("CheckOut", back_populates="revision", cascade="all, delete-orphan")


class RevisionAttribute(Base):
    __tablename__ = "revision_attributes"

    id = Column(Integer, primary_key=True, index=True)
    revision_id = Column(Integer, ForeignKey("treatment_definition_revisions.id"), nullable=False)
    name = Column(String(255), nullable=False)
    defaultValue = Column(Text, nullable=True)

    valueConstraints = relationship("RevisionValueConstraint", back_populates="attribute", cascade="all, delete-orphan", uselist=False)
    revision = relationship("TreatmentDefinitionRevision", back_populates="attributes")


class RevisionValueConstraint(Base):
    __tablename__ = "revision_value_constraints"

    id = Column(Integer, primary_key=True, index=True)
    attribute_id = Column(Integer, ForeignKey("revision_attributes.id"), nullable=False)

    dataType = Column(String(50), nullable=False)
    format = Column(String(50), nullable=True)

    required = Column(Boolean, default=False)
    readOnly = Column(Boolean, default=False)
    multiple = Column(Boolean, default=False)
    range = Column(Boolean, default=False)

    enumValues = Column(Text, nullable=True)

    attribute = relationship("RevisionAttribute", back_populates="valueConstraints")


class CheckOut(Base):
    __tablename__ = "check_outs"

    id = Column(Integer, primary_key=True, index=True)
    revision_id = Column(Integer, ForeignKey("treatment_definition_revisions.id"), nullable=False, index=True)
    working_copy_id = Column(Integer, ForeignKey("treatment_definitions.id"), nullable=True)
    checkedBy = Column(String(255), nullable=True)
    checkTimeStamp = Column(DateTime, default=datetime.utcnow)

    revision = relationship("TreatmentDefinitionRevision", back_populates="checkOuts")


class Attribute(Base):
    __tablename__ = "attributes"

    id = Column(Integer, primary_key=True, index=True)
    treatment_definition_id = Column(Integer, ForeignKey("treatment_definitions.id"), nullable=False)
    name = Column(String(255), nullable=False)
    defaultValue = Column(Text, nullable=True)

    valueConstraints = relationship("ValueConstraint", back_populates="attribute", cascade="all, delete-orphan", uselist=False)
    treatment_definition = relationship("TreatmentDefinition", back_populates="attributes")


class ValueConstraint(Base):
    __tablename__ = "value_constraints"

    id = Column(Integer, primary_key=True, index=True)
    attribute_id = Column(Integer, ForeignKey("attributes.id"), nullable=False)

    dataType = Column(String(50), nullable=False)
    format = Column(String(50), nullable=True)

    required = Column(Boolean, default=False)
    readOnly = Column(Boolean, default=False)
    multiple = Column(Boolean, default=False)
    range = Column(Boolean, default=False)

    enumValues = Column(Text, nullable=True)

    attribute = relationship("Attribute", back_populates="valueConstraints")


class TreatmentDefinitionGroup(Base):
    __tablename__ = "treatment_definition_groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)

    createdBy = Column(String(255), nullable=True)
    creationTimeStamp = Column(DateTime, default=datetime.utcnow)
    modifiedBy = Column(String(255), nullable=True)
    modifiedTimeStamp = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    majorRevision = Column(Integer, default=1)
    minorRevision = Column(Integer, default=0)
    checkout = Column(Boolean, default=False)
    locked = Column(Boolean, default=False)
    status = Column(String(50), default="valid")

    activationStatus = Column(String(50), default="inactive")
    activationError = Column(Text, nullable=True)
    activatedTimeStamp = Column(DateTime, nullable=True)

    parentFolderUri = Column(Text, nullable=True)
    fromRevisionUri = Column(Text, nullable=True)

    version = Column(Integer, default=1)

    members = relationship("GroupMember", back_populates="group", cascade="all, delete-orphan")
    revisions = relationship("TreatmentDefinitionGroupRevision", back_populates="group", cascade="all, delete-orphan")


class TreatmentDefinitionGroupRevision(Base):
    __tablename__ = "treatment_definition_group_revisions"

    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("treatment_definition_groups.id"), nullable=False, index=True)

    name = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)

    createdBy = Column(String(255), nullable=True)
    creationTimeStamp = Column(DateTime, default=datetime.utcnow)
    modifiedBy = Column(String(255), nullable=True)
    modifiedTimeStamp = Column(DateTime, default=datetime.utcnow)

    majorRevision = Column(Integer, default=1)
    minorRevision = Column(Integer, default=0)
    checkout = Column(Boolean, default=False)
    locked = Column(Boolean, default=False)
    status = Column(String(50), default="valid")

    activationStatus = Column(String(50), default="inactive")
    activationError = Column(Text, nullable=True)
    activatedTimeStamp = Column(DateTime, nullable=True)

    parentFolderUri = Column(Text, nullable=True)
    fromRevisionUri = Column(Text, nullable=True)

    group = relationship("TreatmentDefinitionGroup", back_populates="revisions")
    members = relationship("GroupRevisionMember", back_populates="revision", cascade="all, delete-orphan")


class GroupRevisionMember(Base):
    __tablename__ = "treatment_definition_group_revision_members"

    id = Column(Integer, primary_key=True, index=True)
    revision_id = Column(Integer, ForeignKey("treatment_definition_group_revisions.id"), nullable=False, index=True)
    definitionId = Column(Integer, ForeignKey("treatment_definitions.id"), nullable=False, index=True)
    definitionRevisionId = Column(Integer, ForeignKey("treatment_definition_revisions.id"), nullable=True)
    definitionRevisionName = Column(String(255), nullable=True)

    revision = relationship("TreatmentDefinitionGroupRevision", back_populates="members")
    definition = relationship("TreatmentDefinition", foreign_keys=[definitionId])
    definitionRevision = relationship("TreatmentDefinitionRevision", foreign_keys=[definitionRevisionId])

    attributeValueMappings = relationship(
        "GroupRevisionAttributeValueMapping", back_populates="member", cascade="all, delete-orphan"
    )
    attributeNameAliases = relationship(
        "GroupRevisionAttributeNameAlias", back_populates="member", cascade="all, delete-orphan"
    )


class GroupRevisionAttributeValueMapping(Base):
    __tablename__ = "group_revision_attribute_value_mappings"

    id = Column(Integer, primary_key=True, index=True)
    member_id = Column(Integer, ForeignKey("treatment_definition_group_revision_members.id"), nullable=False, index=True)
    attributeId = Column(Integer, ForeignKey("attributes.id"), nullable=True)
    attributeName = Column(String(255), nullable=False)
    mappingType = Column(String(20), nullable=False)
    value = Column(Text, nullable=True)

    member = relationship("GroupRevisionMember", back_populates="attributeValueMappings")


class GroupRevisionAttributeNameAlias(Base):
    __tablename__ = "group_revision_attribute_name_aliases"

    id = Column(Integer, primary_key=True, index=True)
    member_id = Column(Integer, ForeignKey("treatment_definition_group_revision_members.id"), nullable=False, index=True)
    attributeId = Column(Integer, ForeignKey("attributes.id"), nullable=True)
    attributeName = Column(String(255), nullable=False)
    aliasName = Column(String(255), nullable=False)

    member = relationship("GroupRevisionMember", back_populates="attributeNameAliases")


class GroupMember(Base):
    __tablename__ = "treatment_definition_group_members"

    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("treatment_definition_groups.id"), nullable=False, index=True)
    definitionId = Column(Integer, ForeignKey("treatment_definitions.id"), nullable=False, index=True)
    definitionRevisionId = Column(Integer, ForeignKey("treatment_definition_revisions.id"), nullable=True)
    definitionRevisionName = Column(String(255), nullable=True)

    group = relationship("TreatmentDefinitionGroup", back_populates="members")
    definition = relationship("TreatmentDefinition", foreign_keys=[definitionId])
    revision = relationship("TreatmentDefinitionRevision", foreign_keys=[definitionRevisionId])

    attributeValueMappings = relationship(
        "AttributeValueMapping", back_populates="member", cascade="all, delete-orphan"
    )
    attributeNameAliases = relationship(
        "AttributeNameAlias", back_populates="member", cascade="all, delete-orphan"
    )


class AttributeValueMapping(Base):
    __tablename__ = "attribute_value_mappings"

    id = Column(Integer, primary_key=True, index=True)
    member_id = Column(Integer, ForeignKey("treatment_definition_group_members.id"), nullable=False, index=True)
    attributeId = Column(Integer, ForeignKey("attributes.id"), nullable=True)
    attributeName = Column(String(255), nullable=False)
    mappingType = Column(String(20), nullable=False)
    value = Column(Text, nullable=True)

    member = relationship("GroupMember", back_populates="attributeValueMappings")


class AttributeNameAlias(Base):
    __tablename__ = "attribute_name_aliases"

    id = Column(Integer, primary_key=True, index=True)
    member_id = Column(Integer, ForeignKey("treatment_definition_group_members.id"), nullable=False, index=True)
    attributeId = Column(Integer, ForeignKey("attributes.id"), nullable=True)
    attributeName = Column(String(255), nullable=False)
    aliasName = Column(String(255), nullable=False)

    member = relationship("GroupMember", back_populates="attributeNameAliases")
