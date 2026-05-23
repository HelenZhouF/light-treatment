from fastapi import FastAPI, Response, Request, Header, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete, and_, or_
from sqlalchemy.orm import selectinload
from typing import Optional
import json
import traceback
import re

from app.database import init_db, async_session
from app.models import TreatmentDefinition, Attribute, ValueConstraint
from app.models import TreatmentDefinitionRevision, RevisionAttribute, RevisionValueConstraint, CheckOut
from app.models import TreatmentDefinitionGroup, GroupMember, AttributeValueMapping, AttributeNameAlias
from app.schemas import (
    TreatmentDefinitionRoot,
    TreatmentDefinitionCreate,
    TreatmentDefinitionUpdate,
    Link,
    RevisionCreate,
    RevisionBatchQuery,
    TreatmentDefinitionGroupCreate,
    TreatmentDefinitionGroupUpdate,
)

app = FastAPI(
    title="Light Treatment API",
    description="API for light treatment definitions",
    version="1.0.0",
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = []
    for err in exc.errors():
        loc = " -> ".join(str(p) for p in err.get("loc", []))
        msg = err.get("msg", "")
        errors.append(f"{loc}: {msg}" if loc else msg)
    return JSONResponse(
        status_code=400,
        content={"detail": "; ".join(errors) if errors else "Validation failed"},
    )


@app.on_event("startup")
async def startup_event():
    await init_db()


MEDIA_TYPE_DEFINITION = "application/vnd.sas.treatment.definition+json"
MEDIA_TYPE_COLLECTION = "application/vnd.sas.collection+json"
MEDIA_TYPE_SUMMARY = "application/vnd.sas.summary+json"
MEDIA_TYPE_DCM_SUMMARY = "application/vnd.sas.dcm.summary+json"
MEDIA_TYPE_ROOT = "application/vnd.sas.api"
MEDIA_TYPE_REVISION = "application/vnd.sas.treatment.definition+json"
MEDIA_TYPE_GROUP = "application/vnd.sas.treatment.definition.group+json"
MEDIA_TYPE_REVISION_SUMMARY = "application/vnd.sas.revision.summary+json"
MEDIA_TYPE_GROUP_SUMMARY = "application/vnd.sas.treatment.definition.group.summary+json"
MEDIA_TYPE_GROUP_REVISION_SUMMARY = "application/vnd.sas.treatment.definition.group.revisionSummary+json"


BASE_URI = "/treatmentDefinition/definitions"


class FilterParseError(Exception):
    """Exception raised for invalid filter syntax"""
    pass


def parse_filter(filter_str: str):
    """Parse filter expression like eq(name,'Test') or gt(id,5) or in(name,'val1','val2')"""
    
    valid_operators = ['eq', 'gt', 'lt', 'ge', 'le', 'ne', 'contains', 'startsWith', 'in']
    
    value_pattern = r"(?:'([^']*)'|(\d+(?:\.\d+)?))"
    
    patterns = {
        'eq': rf"eq\((\w+),\s*{value_pattern}\)",
        'gt': rf"gt\((\w+),\s*{value_pattern}\)",
        'lt': rf"lt\((\w+),\s*{value_pattern}\)",
        'ge': rf"ge\((\w+),\s*{value_pattern}\)",
        'le': rf"le\((\w+),\s*{value_pattern}\)",
        'ne': rf"ne\((\w+),\s*{value_pattern}\)",
        'contains': rf"contains\((\w+),\s*{value_pattern}\)",
        'startsWith': rf"startsWith\((\w+),\s*{value_pattern}\)",
        'in': r"in\((\w+),\s*((?:'[^']*')(?:\s*,\s*'[^']*')*)\)",
    }
    
    filters = []
    
    found_any = False
    for op, pattern in patterns.items():
        matches = re.findall(pattern, filter_str)
        for match in matches:
            found_any = True
            field_name = match[0]
            
            if op == 'in':
                values_str = match[1]
                values = re.findall(r"'([^']*)'", values_str)
                filters.append({
                    'operator': op,
                    'field': field_name,
                    'values': values
                })
            else:
                str_value = match[1]
                num_value = match[2]
                
                if num_value and num_value != '':
                    value = float(num_value) if '.' in num_value else int(num_value)
                else:
                    value = str_value
                
                filters.append({
                    'operator': op,
                    'field': field_name,
                    'value': value
                })
    
    if not found_any and filter_str:
        valid_ops_pattern = '|'.join(valid_operators)
        if not re.match(rf"^\s*({valid_ops_pattern})\s*\(", filter_str):
            raise FilterParseError(f"Invalid filter syntax: '{filter_str}'. Valid operators are: {', '.join(valid_operators)}")
        
        if not re.match(rf"^\s*({valid_ops_pattern})\s*\(\s*\w+\s*,", filter_str):
            raise FilterParseError(f"Invalid filter syntax: '{filter_str}'. Expected field name after operator")
    
    return filters


def apply_filters(query, filters, model):
    """Apply parsed filters to SQLAlchemy query"""
    conditions = []
    for f in filters:
        field_name = f['field']
        operator = f['operator']
        
        if not hasattr(model, field_name):
            continue
        
        column = getattr(model, field_name)
        
        if operator == 'in':
            values = f.get('values', [])
            if values:
                conditions.append(column.in_(values))
        else:
            value = f['value']
            
            if operator == 'eq':
                conditions.append(column == value)
            elif operator == 'gt':
                conditions.append(column > value)
            elif operator == 'lt':
                conditions.append(column < value)
            elif operator == 'ge':
                conditions.append(column >= value)
            elif operator == 'le':
                conditions.append(column <= value)
            elif operator == 'ne':
                conditions.append(column != value)
            elif operator == 'contains':
                conditions.append(column.contains(str(value)))
            elif operator == 'startsWith':
                conditions.append(column.startswith(str(value)))
    
    if conditions:
        query = query.where(and_(*conditions))
    
    return query


def parse_sort_by(sort_by_str: str):
    """Parse sort parameter like 'name:ascending', '-majorRevision', or 'id'"""
    if sort_by_str.startswith('-'):
        field_name = sort_by_str[1:]
        return field_name, 'descending'
    
    parts = sort_by_str.split(':')
    if len(parts) == 2:
        field_name, direction = parts
        direction = direction.lower()
        if direction not in ('ascending', 'descending'):
            return None, None
        return field_name, direction
    
    return sort_by_str, 'ascending'


def link_to_dict(link: Link) -> dict:
    return link.model_dump()


def generate_definition_links(definition_id: int) -> list[dict]:
    return [
        link_to_dict(Link(rel="self", href=f"{BASE_URI}/{definition_id}", method="GET", type=MEDIA_TYPE_DEFINITION)),
        link_to_dict(Link(rel="up", href=f"{BASE_URI}", method="GET", type=MEDIA_TYPE_COLLECTION)),
        link_to_dict(Link(rel="alternate", href=f"{BASE_URI}/{definition_id}?view=summary", method="GET", type=MEDIA_TYPE_SUMMARY)),
        link_to_dict(Link(rel="update", href=f"{BASE_URI}/{definition_id}", method="PUT", type=MEDIA_TYPE_DEFINITION)),
        link_to_dict(Link(rel="delete", href=f"{BASE_URI}/{definition_id}", method="DELETE")),
        link_to_dict(Link(rel="revisions", href=f"{BASE_URI}/{definition_id}?view=revisionSummary", method="GET", type=MEDIA_TYPE_SUMMARY)),
        link_to_dict(Link(rel="dependencies", href=f"{BASE_URI}/{definition_id}/dependencies", method="GET")),
    ]


def generate_collection_links(start: int, limit: int, count: int) -> list[dict]:
    links = [
        link_to_dict(Link(rel="self", href=f"{BASE_URI}?start={start}&limit={limit}", method="GET", type=MEDIA_TYPE_COLLECTION)),
        link_to_dict(Link(rel="create", href=f"{BASE_URI}", method="POST", type=MEDIA_TYPE_DEFINITION)),
    ]
    if start + limit < count:
        links.append(
            link_to_dict(Link(
                rel="next",
                href=f"{BASE_URI}?start={start + limit}&limit={limit}",
                method="GET",
                type=MEDIA_TYPE_COLLECTION,
            ))
        )
    if start > 0:
        prev_start = max(0, start - limit)
        links.append(
            link_to_dict(Link(
                rel="prev",
                href=f"{BASE_URI}?start={prev_start}&limit={limit}",
                method="GET",
                type=MEDIA_TYPE_COLLECTION,
            ))
        )
    return links


def model_to_response(model: TreatmentDefinition) -> dict:
    data = {
        "id": model.id,
        "name": model.name,
        "description": model.description,
        "createdBy": model.createdBy,
        "creationTimeStamp": model.creationTimeStamp.isoformat() if model.creationTimeStamp else None,
        "modifiedBy": model.modifiedBy,
        "modifiedTimeStamp": model.modifiedTimeStamp.isoformat() if model.modifiedTimeStamp else None,
        "majorRevision": model.majorRevision,
        "minorRevision": model.minorRevision,
        "checkout": model.checkout,
        "locked": model.locked,
        "status": model.status,
        "folderType": model.folderType,
        "sourceRevisionUri": model.sourceRevisionUri,
        "copyTimeStamp": model.copyTimeStamp.isoformat() if model.copyTimeStamp else None,
        "version": model.version,
        "attributes": [],
        "links": generate_definition_links(model.id),
    }
    for attr in model.attributes:
        attr_data = {
            "id": attr.id,
            "name": attr.name,
            "defaultValue": attr.defaultValue,
        }
        if attr.valueConstraints:
            vc = attr.valueConstraints
            attr_data["valueConstraints"] = {
                "id": vc.id,
                "dataType": vc.dataType,
                "format": vc.format,
                "required": vc.required,
                "readOnly": vc.readOnly,
                "multiple": vc.multiple,
                "range": vc.range,
                "enum": json.loads(vc.enumValues) if vc.enumValues else None,
            }
        data["attributes"].append(attr_data)
    return data


def model_to_summary(model: TreatmentDefinition) -> dict:
    return {
        "id": model.id,
        "name": model.name,
        "description": model.description,
        "createdBy": model.createdBy,
        "creationTimeStamp": model.creationTimeStamp.isoformat() if model.creationTimeStamp else None,
        "modifiedBy": model.modifiedBy,
        "modifiedTimeStamp": model.modifiedTimeStamp.isoformat() if model.modifiedTimeStamp else None,
        "majorRevision": model.majorRevision,
        "minorRevision": model.minorRevision,
        "checkout": model.checkout,
        "locked": model.locked,
        "status": model.status,
        "links": generate_definition_links(model.id),
    }


def model_to_revision_summary(model: TreatmentDefinition) -> dict:
    return {
        "id": model.id,
        "name": model.name,
        "majorRevision": model.majorRevision,
        "minorRevision": model.minorRevision,
        "status": model.status,
        "links": generate_definition_links(model.id),
    }


async def create_attributes_from_schema(db: AsyncSession, treatment_def_id: int, attributes: list):
    for attr_data in attributes:
        attr = Attribute(
            treatment_definition_id=treatment_def_id,
            name=attr_data.name,
            defaultValue=attr_data.defaultValue,
        )
        db.add(attr)
        await db.flush()

        if attr_data.valueConstraints:
            vc = attr_data.valueConstraints
            vc_obj = ValueConstraint(
                attribute_id=attr.id,
                dataType=vc.dataType,
                format=vc.format,
                required=vc.required or False,
                readOnly=vc.readOnly or False,
                multiple=vc.multiple or False,
                range=vc.range or False,
                enumValues=json.dumps(vc.enum) if vc.enum else None,
            )
            db.add(vc_obj)


@app.get(
    "/treatmentDefinition",
    response_model=TreatmentDefinitionRoot,
    responses={
        200: {
            "content": {MEDIA_TYPE_ROOT: {}},
            "description": "Root entry point for treatment definitions service",
        }
    },
)
async def get_treatment_definition_root():
    root = TreatmentDefinitionRoot(
        links=[
            Link(
                rel="treatmentDefinitions",
                href=f"{BASE_URI}",
                method="GET",
                type=MEDIA_TYPE_COLLECTION,
            ),
            Link(
                rel="createTreatmentDefinition",
                href=f"{BASE_URI}",
                method="POST",
                type=MEDIA_TYPE_DEFINITION,
            ),
        ]
    )
    return JSONResponse(
        content=root.model_dump(),
        media_type=MEDIA_TYPE_ROOT,
    )


@app.get(
    f"{BASE_URI}",
    responses={
        200: {
            "content": {
                MEDIA_TYPE_COLLECTION: {},
                MEDIA_TYPE_SUMMARY: {},
            },
            "description": "Collection of treatment definitions",
        }
    },
)
async def get_definitions(
    request: Request,
    start: int = Query(0, ge=0, description="Start index for pagination"),
    limit: int = Query(10, ge=1, le=100, description="Maximum items to return"),
    filter: Optional[str] = Query(None, description="Filter criteria (e.g., eq(name,'Test'))"),
    sortedBy: Optional[str] = Query(None, description="Sort by field (e.g., -majorRevision, name:ascending)"),
    accept_item: Optional[str] = Header(None, alias="Accept-Item"),
):
    try:
        parsed_filters = parse_filter(filter) if filter else []
    except FilterParseError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    async with async_session() as db:
        query = select(TreatmentDefinition).options(
            selectinload(TreatmentDefinition.attributes).selectinload(Attribute.valueConstraints)
        )

        if filter:
            query = apply_filters(query, parsed_filters, TreatmentDefinition)

        if sortedBy:
            sort_field, direction = parse_sort_by(sortedBy)
            if sort_field and hasattr(TreatmentDefinition, sort_field):
                column = getattr(TreatmentDefinition, sort_field)
                if direction == 'descending':
                    query = query.order_by(column.desc())
                else:
                    query = query.order_by(column)
            else:
                query = query.order_by(TreatmentDefinition.id)
        else:
            query = query.order_by(TreatmentDefinition.id)

        count_query = select(func.count()).select_from(TreatmentDefinition)
        if filter:
            count_query = apply_filters(count_query, parsed_filters, TreatmentDefinition)
        result = await db.execute(count_query)
        count = result.scalar()

        query = query.offset(start).limit(limit)
        result = await db.execute(query)
        definitions = result.scalars().all()

        use_summary = accept_item == MEDIA_TYPE_SUMMARY

        if use_summary:
            items = [model_to_summary(d) for d in definitions]
            media_type = MEDIA_TYPE_SUMMARY
        else:
            items = [model_to_response(d) for d in definitions]
            media_type = MEDIA_TYPE_COLLECTION

        collection = {
            "items": items,
            "start": start,
            "limit": limit,
            "count": count,
            "links": generate_collection_links(start, limit, count),
        }

        return JSONResponse(content=collection, media_type=media_type)


@app.get(
    f"{BASE_URI}/{{definition_id}}",
    responses={
        200: {
            "content": {
                MEDIA_TYPE_DEFINITION: {},
                MEDIA_TYPE_SUMMARY: {},
            },
            "description": "Treatment definition",
        },
        404: {"description": "Definition not found"},
    },
)
async def get_definition(
    definition_id: int,
    request: Request,
    view: Optional[str] = Query(None, description="View type: summary or revisionSummary"),
    accept_item: Optional[str] = Header(None, alias="Accept-Item"),
):
    async with async_session() as db:
        query = select(TreatmentDefinition).options(
            selectinload(TreatmentDefinition.attributes).selectinload(Attribute.valueConstraints)
        ).where(TreatmentDefinition.id == definition_id)
        result = await db.execute(query)
        definition = result.scalar_one_or_none()

        if not definition:
            raise HTTPException(status_code=404, detail="Definition not found")

        url_fragment = request.url.fragment if request.url.fragment else None
        
        is_summary = (view == "summary") or (url_fragment == "summary")
        is_revision = (view == "revisionSummary") or (url_fragment == "revisionSummary")

        if is_revision or accept_item == "application/vnd.sas.revision.summary+json":
            data = model_to_revision_summary(definition)
            media_type = MEDIA_TYPE_SUMMARY
        elif is_summary or accept_item == MEDIA_TYPE_SUMMARY:
            data = model_to_summary(definition)
            media_type = MEDIA_TYPE_SUMMARY
        else:
            data = model_to_response(definition)
            media_type = MEDIA_TYPE_DEFINITION

        return JSONResponse(content=data, media_type=media_type)


@app.post(
    f"{BASE_URI}",
    status_code=201,
    responses={
        201: {
            "content": {MEDIA_TYPE_DEFINITION: {}},
            "description": "Created treatment definition",
        },
        400: {"description": "Invalid input"},
    },
)
async def create_definition(
    definition: TreatmentDefinitionCreate,
    request: Request,
):
    try:
        async with async_session() as db:
            new_def = TreatmentDefinition(
                name=definition.name,
                description=definition.description,
                createdBy="system",
                modifiedBy="system",
            )
            db.add(new_def)
            await db.flush()

            if definition.attributes:
                await create_attributes_from_schema(db, new_def.id, definition.attributes)

            await db.commit()
            def_id = new_def.id
            def_version = new_def.version

        async with async_session() as db:
            query = select(TreatmentDefinition).options(
                selectinload(TreatmentDefinition.attributes).selectinload(Attribute.valueConstraints)
            ).where(TreatmentDefinition.id == def_id)
            result = await db.execute(query)
            created_def = result.scalar_one()

            data = model_to_response(created_def)
            response = JSONResponse(
                content=data,
                status_code=201,
                media_type=MEDIA_TYPE_DEFINITION,
            )
            response.headers["Location"] = f"{BASE_URI}/{created_def.id}"
            response.headers["ETag"] = str(def_version)
            return response
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=str(e))


@app.put(
    f"{BASE_URI}/{{definition_id}}",
    responses={
        200: {
            "content": {MEDIA_TYPE_DEFINITION: {}},
            "description": "Updated treatment definition",
        },
        400: {"description": "Invalid input"},
        404: {"description": "Definition not found"},
        412: {"description": "Precondition failed (ETag mismatch)"},
    },
)
async def update_definition(
    definition_id: int,
    definition: TreatmentDefinitionUpdate,
    request: Request,
    if_match: Optional[str] = Header(None, alias="If-Match"),
):
    try:
        async with async_session() as db:
            query = select(TreatmentDefinition).options(
                selectinload(TreatmentDefinition.attributes).selectinload(Attribute.valueConstraints)
            ).where(TreatmentDefinition.id == definition_id)
            result = await db.execute(query)
            existing = result.scalar_one_or_none()

            if not existing:
                raise HTTPException(status_code=404, detail="Definition not found")

            if if_match and str(existing.version) != if_match:
                raise HTTPException(status_code=412, detail="ETag mismatch")

            if definition.name is not None:
                existing.name = definition.name
            if definition.description is not None:
                existing.description = definition.description

            existing.modifiedBy = "system"
            existing.version = existing.version + 1
            existing.minorRevision = existing.minorRevision + 1

            if definition.attributes is not None:
                await db.execute(delete(ValueConstraint).where(
                    ValueConstraint.attribute_id.in_(
                        select(Attribute.id).where(Attribute.treatment_definition_id == definition_id)
                    )
                ))
                await db.execute(delete(Attribute).where(Attribute.treatment_definition_id == definition_id))

                await create_attributes_from_schema(db, definition_id, definition.attributes)

            await db.commit()
            def_version = existing.version

        async with async_session() as db:
            query = select(TreatmentDefinition).options(
                selectinload(TreatmentDefinition.attributes).selectinload(Attribute.valueConstraints)
            ).where(TreatmentDefinition.id == definition_id)
            result = await db.execute(query)
            updated_def = result.scalar_one()

            data = model_to_response(updated_def)
            response = JSONResponse(
                content=data,
                status_code=200,
                media_type=MEDIA_TYPE_DEFINITION,
            )
            response.headers["ETag"] = str(def_version)
            return response
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=str(e))


@app.delete(
    f"{BASE_URI}/{{definition_id}}",
    status_code=204,
    responses={
        204: {"description": "Definition deleted successfully"},
        404: {"description": "Definition not found"},
    },
)
async def delete_definition(
    definition_id: int,
    request: Request,
):
    try:
        async with async_session() as db:
            query = select(TreatmentDefinition).where(TreatmentDefinition.id == definition_id)
            result = await db.execute(query)
            existing = result.scalar_one_or_none()

            if not existing:
                raise HTTPException(status_code=404, detail="Definition not found")

            await db.execute(delete(ValueConstraint).where(
                ValueConstraint.attribute_id.in_(
                    select(Attribute.id).where(Attribute.treatment_definition_id == definition_id)
                )
            ))
            await db.execute(delete(Attribute).where(Attribute.treatment_definition_id == definition_id))
            await db.delete(existing)
            await db.commit()

            return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=str(e))


@app.get(
    f"{BASE_URI}/{{definition_id}}/dependencies",
    responses={
        200: {
            "content": {MEDIA_TYPE_COLLECTION: {}},
            "description": "Direct dependencies of the definition",
        },
        404: {"description": "Definition not found"},
    },
)
async def get_definition_dependencies(
    definition_id: int,
    request: Request,
):
    async with async_session() as db:
        query = select(TreatmentDefinition).where(TreatmentDefinition.id == definition_id)
        result = await db.execute(query)
        definition = result.scalar_one_or_none()

        if not definition:
            raise HTTPException(status_code=404, detail="Definition not found")

        collection = {
            "items": [],
            "start": 0,
            "limit": 0,
            "count": 0,
            "links": [
                link_to_dict(Link(rel="self", href=f"{BASE_URI}/{definition_id}/dependencies", method="GET", type=MEDIA_TYPE_COLLECTION)),
                link_to_dict(Link(rel="up", href=f"{BASE_URI}/{definition_id}", method="GET", type=MEDIA_TYPE_DEFINITION)),
            ],
        }

        return JSONResponse(content=collection, media_type=MEDIA_TYPE_COLLECTION)


# ------------------------- Revision helpers -------------------------

REVISION_BASE_URI = BASE_URI


def revision_uri(definition_id: int, revision_id=None) -> str:
    if revision_id is None:
        return f"{BASE_URI}/{definition_id}/revisions"
    return f"{BASE_URI}/{definition_id}/revisions/{revision_id}"


def generate_revision_links(definition_id: int, revision_id: int) -> list[dict]:
    uri = revision_uri(definition_id, revision_id)
    return [
        link_to_dict(Link(rel="self", href=uri, method="GET", type=MEDIA_TYPE_REVISION)),
        link_to_dict(Link(rel="up", href=revision_uri(definition_id), method="GET", type=MEDIA_TYPE_COLLECTION)),
        link_to_dict(Link(rel="alternate", href=f"{uri}#summary", method="GET", type=MEDIA_TYPE_SUMMARY)),
        link_to_dict(Link(rel="alternate", href=f"{uri}#revisionSummary", method="GET", type=MEDIA_TYPE_DCM_SUMMARY)),
        link_to_dict(Link(rel="delete", href=uri, method="DELETE")),
        link_to_dict(Link(rel="checkOuts", href=f"{uri}/checkOuts", method="GET", type=MEDIA_TYPE_COLLECTION)),
    ]


def generate_revision_collection_links(definition_id: int, start: int, limit: int, count: int) -> list[dict]:
    uri = revision_uri(definition_id)
    links = [
        link_to_dict(Link(rel="self", href=f"{uri}?start={start}&limit={limit}", method="GET", type=MEDIA_TYPE_COLLECTION)),
        link_to_dict(Link(rel="up", href=f"{BASE_URI}/{definition_id}", method="GET", type=MEDIA_TYPE_DEFINITION)),
        link_to_dict(Link(rel="create", href=uri, method="POST", type=MEDIA_TYPE_REVISION)),
    ]
    if start + limit < count:
        links.append(
            link_to_dict(Link(
                rel="next",
                href=f"{uri}?start={start + limit}&limit={limit}",
                method="GET",
                type=MEDIA_TYPE_COLLECTION,
            ))
        )
    if start > 0:
        prev_start = max(0, start - limit)
        links.append(
            link_to_dict(Link(
                rel="prev",
                href=f"{uri}?start={prev_start}&limit={limit}",
                method="GET",
                type=MEDIA_TYPE_COLLECTION,
            ))
        )
    return links


def revision_model_to_response(rev: TreatmentDefinitionRevision) -> dict:
    data = {
        "id": rev.id,
        "name": rev.name,
        "description": rev.description,
        "createdBy": rev.createdBy,
        "creationTimeStamp": rev.creationTimeStamp.isoformat() if rev.creationTimeStamp else None,
        "modifiedBy": rev.modifiedBy,
        "modifiedTimeStamp": rev.modifiedTimeStamp.isoformat() if rev.modifiedTimeStamp else None,
        "majorRevision": rev.majorRevision,
        "minorRevision": rev.minorRevision,
        "checkout": rev.checkout,
        "locked": rev.locked,
        "status": rev.status,
        "folderType": rev.folderType,
        "sourceRevisionUri": rev.sourceRevisionUri,
        "copyTimeStamp": rev.copyTimeStamp.isoformat() if rev.copyTimeStamp else None,
        "fromRevisionUri": rev.fromRevisionUri,
        "isActive": rev.isActive,
        "attributes": [],
        "links": generate_revision_links(rev.treatment_definition_id, rev.id),
    }
    for attr in rev.attributes:
        attr_data = {
            "id": attr.id,
            "name": attr.name,
            "defaultValue": attr.defaultValue,
        }
        if attr.valueConstraints:
            vc = attr.valueConstraints
            attr_data["valueConstraints"] = {
                "id": vc.id,
                "dataType": vc.dataType,
                "format": vc.format,
                "required": vc.required,
                "readOnly": vc.readOnly,
                "multiple": vc.multiple,
                "range": vc.range,
                "enum": json.loads(vc.enumValues) if vc.enumValues else None,
            }
        data["attributes"].append(attr_data)
    return data


def revision_model_to_summary(rev: TreatmentDefinitionRevision) -> dict:
    return {
        "id": rev.id,
        "name": rev.name,
        "description": rev.description,
        "createdBy": rev.createdBy,
        "creationTimeStamp": rev.creationTimeStamp.isoformat() if rev.creationTimeStamp else None,
        "modifiedBy": rev.modifiedBy,
        "modifiedTimeStamp": rev.modifiedTimeStamp.isoformat() if rev.modifiedTimeStamp else None,
        "majorRevision": rev.majorRevision,
        "minorRevision": rev.minorRevision,
        "checkout": rev.checkout,
        "locked": rev.locked,
        "status": rev.status,
        "isActive": rev.isActive,
        "links": generate_revision_links(rev.treatment_definition_id, rev.id),
    }


def revision_model_to_revision_summary(rev: TreatmentDefinitionRevision) -> dict:
    return {
        "id": rev.id,
        "name": rev.name,
        "majorRevision": rev.majorRevision,
        "minorRevision": rev.minorRevision,
        "status": rev.status,
        "isActive": rev.isActive,
        "links": generate_revision_links(rev.treatment_definition_id, rev.id),
    }


async def create_revision_attributes_from_source(db: AsyncSession, revision_id: int, source_attributes: list):
    for src_attr in source_attributes:
        attr = RevisionAttribute(
            revision_id=revision_id,
            name=src_attr.name,
            defaultValue=src_attr.defaultValue,
        )
        db.add(attr)
        await db.flush()

        if src_attr.valueConstraints:
            src_vc = src_attr.valueConstraints
            vc = RevisionValueConstraint(
                attribute_id=attr.id,
                dataType=src_vc.dataType,
                format=src_vc.format,
                required=src_vc.required or False,
                readOnly=src_vc.readOnly or False,
                multiple=src_vc.multiple or False,
                range=src_vc.range or False,
                enumValues=src_vc.enumValues,
            )
            db.add(vc)


# ------------------------- Revision API -------------------------


@app.get(
    f"{BASE_URI}/{{definition_id}}/revisions",
    responses={
        200: {
            "content": {
                MEDIA_TYPE_COLLECTION: {},
                MEDIA_TYPE_SUMMARY: {},
                MEDIA_TYPE_DCM_SUMMARY: {},
            },
            "description": "Collection of treatment definition revisions",
        },
        404: {"description": "Definition not found"},
    },
)
async def get_revisions(
    definition_id: int,
    request: Request,
    start: int = Query(0, ge=0, description="Start index for pagination"),
    limit: int = Query(10, ge=1, le=100, description="Maximum items to return"),
    filter: Optional[str] = Query(None, description="Filter criteria (e.g., eq(status,'valid'))"),
    sortedBy: Optional[str] = Query(None, description="Sort by field (e.g., -majorRevision, creationTimeStamp:descending)"),
    accept_item: Optional[str] = Header(None, alias="Accept-Item"),
):
    async with async_session() as db:
        def_query = select(TreatmentDefinition.id).where(TreatmentDefinition.id == definition_id)
        def_result = await db.execute(def_query)
        if not def_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Definition not found")

    try:
        parsed_filters = parse_filter(filter) if filter else []
    except FilterParseError as e:
        raise HTTPException(status_code=400, detail=str(e))

    async with async_session() as db:
        query = select(TreatmentDefinitionRevision).options(
            selectinload(TreatmentDefinitionRevision.attributes).selectinload(RevisionAttribute.valueConstraints)
        ).where(TreatmentDefinitionRevision.treatment_definition_id == definition_id)

        if filter:
            query = apply_filters(query, parsed_filters, TreatmentDefinitionRevision)

        if sortedBy:
            sort_field, direction = parse_sort_by(sortedBy)
            if sort_field and hasattr(TreatmentDefinitionRevision, sort_field):
                column = getattr(TreatmentDefinitionRevision, sort_field)
                if direction == 'descending':
                    query = query.order_by(column.desc())
                else:
                    query = query.order_by(column)
            else:
                query = query.order_by(TreatmentDefinitionRevision.id)
        else:
            query = query.order_by(TreatmentDefinitionRevision.id)

        count_query = select(func.count()).select_from(TreatmentDefinitionRevision).where(
            TreatmentDefinitionRevision.treatment_definition_id == definition_id
        )
        if filter:
            count_query = apply_filters(count_query, parsed_filters, TreatmentDefinitionRevision)
        count_result = await db.execute(count_query)
        count = count_result.scalar()

        query = query.offset(start).limit(limit)
        result = await db.execute(query)
        revisions = result.scalars().all()

        if accept_item == MEDIA_TYPE_DCM_SUMMARY:
            items = [revision_model_to_revision_summary(r) for r in revisions]
            media_type = MEDIA_TYPE_DCM_SUMMARY
        elif accept_item == MEDIA_TYPE_SUMMARY:
            items = [revision_model_to_summary(r) for r in revisions]
            media_type = MEDIA_TYPE_SUMMARY
        else:
            items = [revision_model_to_response(r) for r in revisions]
            media_type = MEDIA_TYPE_COLLECTION

        collection = {
            "items": items,
            "start": start,
            "limit": limit,
            "count": count,
            "links": generate_revision_collection_links(definition_id, start, limit, count),
        }

        return JSONResponse(content=collection, media_type=media_type)


def _resolve_revision_alias(alias: str):
    """Return a filter predicate for @current / @active aliases, or None if regular id."""
    if alias == "@current":
        return None, "current"
    if alias == "@active":
        return None, "active"
    try:
        return int(alias), None
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail=f"Invalid revision id: {alias}")


@app.get(
    f"{BASE_URI}/{{definition_id}}/revisions/{{revision_id}}",
    responses={
        200: {
            "content": {
                MEDIA_TYPE_REVISION: {},
                MEDIA_TYPE_SUMMARY: {},
                MEDIA_TYPE_DCM_SUMMARY: {},
            },
            "description": "A treatment definition revision",
        },
        404: {"description": "Definition or revision not found"},
    },
)
async def get_revision(
    definition_id: int,
    revision_id: str,
    request: Request,
    accept_item: Optional[str] = Header(None, alias="Accept-Item"),
):
    async with async_session() as db:
        def_query = select(TreatmentDefinition.id).where(TreatmentDefinition.id == definition_id)
        def_result = await db.execute(def_query)
        if not def_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Definition not found")

        base_query = select(TreatmentDefinitionRevision).options(
            selectinload(TreatmentDefinitionRevision.attributes).selectinload(RevisionAttribute.valueConstraints)
        ).where(TreatmentDefinitionRevision.treatment_definition_id == definition_id)

        resolved_id, alias = _resolve_revision_alias(revision_id)

        if alias == "active":
            query = base_query.where(TreatmentDefinitionRevision.isActive.is_(True)).order_by(
                TreatmentDefinitionRevision.majorRevision.desc(),
                TreatmentDefinitionRevision.minorRevision.desc(),
            )
        elif alias == "current":
            query = base_query.order_by(
                TreatmentDefinitionRevision.majorRevision.desc(),
                TreatmentDefinitionRevision.minorRevision.desc(),
                TreatmentDefinitionRevision.id.desc(),
            )
        else:
            query = base_query.where(TreatmentDefinitionRevision.id == resolved_id)

        query = query.limit(1)
        result = await db.execute(query)
        revision = result.scalar_one_or_none()

        if not revision:
            raise HTTPException(status_code=404, detail="Revision not found")

        url_fragment = request.url.fragment if request.url.fragment else None

        if url_fragment == "revisionSummary" or accept_item == MEDIA_TYPE_DCM_SUMMARY:
            data = revision_model_to_revision_summary(revision)
            media_type = MEDIA_TYPE_DCM_SUMMARY
        elif url_fragment == "summary" or accept_item == MEDIA_TYPE_SUMMARY:
            data = revision_model_to_summary(revision)
            media_type = MEDIA_TYPE_SUMMARY
        else:
            data = revision_model_to_response(revision)
            media_type = MEDIA_TYPE_REVISION

        return JSONResponse(content=data, media_type=media_type)


@app.post(
    f"{BASE_URI}/{{definition_id}}/revisions",
    status_code=201,
    responses={
        201: {
            "content": {MEDIA_TYPE_REVISION: {}},
            "description": "Created treatment definition revision",
        },
        400: {"description": "Invalid input"},
        404: {"description": "Definition not found"},
    },
)
async def create_revision(
    definition_id: int,
    revision_create: Optional[RevisionCreate] = None,
    request: Request = None,
):
    try:
        async with async_session() as db:
            def_query = select(TreatmentDefinition).options(
                selectinload(TreatmentDefinition.attributes).selectinload(Attribute.valueConstraints)
            ).where(TreatmentDefinition.id == definition_id)
            def_result = await db.execute(def_query)
            definition = def_result.scalar_one_or_none()
            if not definition:
                raise HTTPException(status_code=404, detail="Definition not found")

            revision_type = "minor"
            from_revision_uri = None
            override_name = None
            override_description = None
            source_revision = None

            if revision_create is not None:
                revision_type = revision_create.revisionType or "minor"
                from_revision_uri = revision_create.fromRevisionUri
                override_name = revision_create.name
                override_description = revision_create.description

            if from_revision_uri:
                rev_result = await db.execute(
                    select(TreatmentDefinitionRevision).options(
                        selectinload(TreatmentDefinitionRevision.attributes).selectinload(RevisionAttribute.valueConstraints)
                    ).where(TreatmentDefinitionRevision.fromRevisionUri == from_revision_uri)
                )
                source_revision = rev_result.scalar_one_or_none()

            if source_revision:
                source_major = source_revision.majorRevision or 1
                source_minor = source_revision.minorRevision or 0
            else:
                max_result = await db.execute(
                    select(
                        func.max(TreatmentDefinitionRevision.majorRevision),
                        func.max(TreatmentDefinitionRevision.minorRevision),
                    ).where(TreatmentDefinitionRevision.treatment_definition_id == definition_id)
                )
                row = max_result.one()
                max_major, max_minor = row
                if max_major is None:
                    source_major = definition.majorRevision or 1
                    source_minor = definition.minorRevision or 0
                else:
                    source_major = max_major
                    source_minor = max_minor or 0

            if revision_type == "major":
                new_major = source_major + 1
                new_minor = 0
            else:
                new_major = source_major
                new_minor = source_minor + 1

            new_rev = TreatmentDefinitionRevision(
                treatment_definition_id=definition_id,
                name=override_name or definition.name,
                description=override_description or definition.description,
                createdBy="system",
                modifiedBy="system",
                majorRevision=new_major,
                minorRevision=new_minor,
                checkout=False,
                locked=definition.locked or False,
                status=definition.status or "valid",
                folderType=definition.folderType,
                sourceRevisionUri=definition.sourceRevisionUri,
                copyTimeStamp=definition.copyTimeStamp,
                fromRevisionUri=from_revision_uri,
                isActive=False,
            )
            db.add(new_rev)
            await db.flush()

            if source_revision and source_revision.attributes:
                await create_revision_attributes_from_source(db, new_rev.id, list(source_revision.attributes))
            else:
                await create_revision_attributes_from_source(db, new_rev.id, list(definition.attributes))

            await db.commit()
            new_rev_id = new_rev.id

        async with async_session() as db:
            query = select(TreatmentDefinitionRevision).options(
                selectinload(TreatmentDefinitionRevision.attributes).selectinload(RevisionAttribute.valueConstraints)
            ).where(TreatmentDefinitionRevision.id == new_rev_id)
            result = await db.execute(query)
            created = result.scalar_one()

            data = revision_model_to_response(created)
            response = JSONResponse(
                content=data,
                status_code=201,
                media_type=MEDIA_TYPE_REVISION,
            )
            response.headers["Location"] = revision_uri(definition_id, created.id)
            return response
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=str(e))


@app.delete(
    f"{BASE_URI}/{{definition_id}}/revisions/{{revision_id}}",
    status_code=204,
    responses={
        204: {"description": "Revision deleted successfully"},
        404: {"description": "Definition or revision not found"},
    },
)
async def delete_revision(
    definition_id: int,
    revision_id: int,
    request: Request,
):
    try:
        async with async_session() as db:
            def_query = select(TreatmentDefinition.id).where(TreatmentDefinition.id == definition_id)
            def_result = await db.execute(def_query)
            if not def_result.scalar_one_or_none():
                raise HTTPException(status_code=404, detail="Definition not found")

            query = select(TreatmentDefinitionRevision).where(
                TreatmentDefinitionRevision.id == revision_id,
                TreatmentDefinitionRevision.treatment_definition_id == definition_id,
            )
            result = await db.execute(query)
            existing = result.scalar_one_or_none()
            if not existing:
                raise HTTPException(status_code=404, detail="Revision not found")

            await db.execute(delete(RevisionValueConstraint).where(
                RevisionValueConstraint.attribute_id.in_(
                    select(RevisionAttribute.id).where(RevisionAttribute.revision_id == revision_id)
                )
            ))
            await db.execute(delete(RevisionAttribute).where(RevisionAttribute.revision_id == revision_id))
            await db.execute(delete(CheckOut).where(CheckOut.revision_id == revision_id))
            await db.delete(existing)
            await db.commit()

            return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=str(e))


@app.get(
    f"{BASE_URI}/{{definition_id}}/revisions/{{revision_id}}/checkOuts",
    responses={
        200: {
            "content": {MEDIA_TYPE_COLLECTION: {}},
            "description": "Check-outs associated with the revision",
        },
        404: {"description": "Definition or revision not found"},
    },
)
async def get_revision_checkouts(
    definition_id: int,
    revision_id: int,
    request: Request,
):
    async with async_session() as db:
        def_query = select(TreatmentDefinition.id).where(TreatmentDefinition.id == definition_id)
        def_result = await db.execute(def_query)
        if not def_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Definition not found")

        rev_query = select(TreatmentDefinitionRevision.id).where(
            TreatmentDefinitionRevision.id == revision_id,
            TreatmentDefinitionRevision.treatment_definition_id == definition_id,
        )
        rev_result = await db.execute(rev_query)
        if not rev_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Revision not found")

        query = select(CheckOut).where(CheckOut.revision_id == revision_id)
        result = await db.execute(query)
        checkouts = result.scalars().all()

        items = []
        for co in checkouts:
            uri = revision_uri(definition_id, revision_id)
            items.append({
                "id": co.id,
                "workingCopyId": co.working_copy_id,
                "checkedBy": co.checkedBy,
                "checkTimeStamp": co.checkTimeStamp.isoformat() if co.checkTimeStamp else None,
                "links": [
                    link_to_dict(Link(rel="self", href=f"{uri}/checkOuts/{co.id}", method="GET")),
                    link_to_dict(Link(rel="up", href=uri, method="GET", type=MEDIA_TYPE_REVISION)),
                ],
            })

        uri = revision_uri(definition_id, revision_id)
        collection = {
            "items": items,
            "start": 0,
            "limit": len(items),
            "count": len(items),
            "links": [
                link_to_dict(Link(rel="self", href=f"{uri}/checkOuts", method="GET", type=MEDIA_TYPE_COLLECTION)),
                link_to_dict(Link(rel="up", href=uri, method="GET", type=MEDIA_TYPE_REVISION)),
            ],
        }
        return JSONResponse(content=collection, media_type=MEDIA_TYPE_COLLECTION)


# ------------------------- Batch query API -------------------------


@app.post(
    "/treatmentDefinition/definitionRevisions",
    responses={
        200: {
            "content": {MEDIA_TYPE_COLLECTION: {}},
            "description": "Batch query result for revisions",
        },
        400: {"description": "Invalid input"},
    },
)
async def batch_query_revisions(
    body: RevisionBatchQuery,
    request: Request,
    accept_item: Optional[str] = Header(None, alias="Accept-Item"),
):
    try:
        ids = body.selection.resources or []
        if not ids:
            collection = {
                "items": [],
                "start": 0,
                "limit": 0,
                "count": 0,
                "links": [
                    link_to_dict(Link(rel="self", href="/treatmentDefinition/definitionRevisions", method="POST", type=MEDIA_TYPE_COLLECTION)),
                ],
            }
            return JSONResponse(content=collection, media_type=MEDIA_TYPE_COLLECTION)

        async with async_session() as db:
            query = select(TreatmentDefinitionRevision).options(
                selectinload(TreatmentDefinitionRevision.attributes).selectinload(RevisionAttribute.valueConstraints)
            ).where(TreatmentDefinitionRevision.id.in_(ids))
            result = await db.execute(query)
            revisions = result.scalars().all()

            if accept_item == MEDIA_TYPE_DCM_SUMMARY:
                items = [revision_model_to_revision_summary(r) for r in revisions]
                media_type = MEDIA_TYPE_DCM_SUMMARY
            elif accept_item == MEDIA_TYPE_SUMMARY:
                items = [revision_model_to_summary(r) for r in revisions]
                media_type = MEDIA_TYPE_SUMMARY
            else:
                items = [revision_model_to_response(r) for r in revisions]
                media_type = MEDIA_TYPE_COLLECTION

            collection = {
                "items": items,
                "start": 0,
                "limit": len(items),
                "count": len(items),
                "links": [
                    link_to_dict(Link(rel="self", href="/treatmentDefinition/definitionRevisions", method="POST", type=MEDIA_TYPE_COLLECTION)),
                ],
            }
            return JSONResponse(content=collection, media_type=media_type)
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=str(e))


# ------------------------- Treatment Definition Group API -------------------------

GROUP_BASE_URI = "/treatmentDefinition/definitionGroups"


def generate_group_links(group_id: int) -> list[dict]:
    return [
        link_to_dict(Link(rel="self", href=f"{GROUP_BASE_URI}/{group_id}", method="GET", type=MEDIA_TYPE_GROUP)),
        link_to_dict(Link(rel="up", href=f"{GROUP_BASE_URI}", method="GET", type=MEDIA_TYPE_COLLECTION)),
        link_to_dict(Link(rel="alternate", href=f"{GROUP_BASE_URI}/{group_id}?view=summary", method="GET", type=MEDIA_TYPE_SUMMARY)),
        link_to_dict(Link(rel="update", href=f"{GROUP_BASE_URI}/{group_id}", method="PUT", type=MEDIA_TYPE_GROUP)),
        link_to_dict(Link(rel="delete", href=f"{GROUP_BASE_URI}/{group_id}", method="DELETE")),
        link_to_dict(Link(rel="dependencies", href=f"{GROUP_BASE_URI}/{group_id}/dependencies", method="GET")),
    ]


def generate_group_collection_links(start: int, limit: int, count: int) -> list[dict]:
    links = [
        link_to_dict(Link(rel="self", href=f"{GROUP_BASE_URI}?start={start}&limit={limit}", method="GET", type=MEDIA_TYPE_COLLECTION)),
        link_to_dict(Link(rel="create", href=f"{GROUP_BASE_URI}", method="POST", type=MEDIA_TYPE_GROUP)),
    ]
    if start + limit < count:
        links.append(
            link_to_dict(Link(
                rel="next",
                href=f"{GROUP_BASE_URI}?start={start + limit}&limit={limit}",
                method="GET",
                type=MEDIA_TYPE_COLLECTION,
            ))
        )
    if start > 0:
        prev_start = max(0, start - limit)
        links.append(
            link_to_dict(Link(
                rel="prev",
                href=f"{GROUP_BASE_URI}?start={prev_start}&limit={limit}",
                method="GET",
                type=MEDIA_TYPE_COLLECTION,
            ))
        )
    return links


def group_model_to_response(model: TreatmentDefinitionGroup) -> dict:
    data = {
        "id": model.id,
        "name": model.name,
        "description": model.description,
        "createdBy": model.createdBy,
        "creationTimeStamp": model.creationTimeStamp.isoformat() if model.creationTimeStamp else None,
        "modifiedBy": model.modifiedBy,
        "modifiedTimeStamp": model.modifiedTimeStamp.isoformat() if model.modifiedTimeStamp else None,
        "majorRevision": model.majorRevision,
        "minorRevision": model.minorRevision,
        "checkout": model.checkout,
        "locked": model.locked,
        "status": model.status,
        "activationStatus": model.activationStatus,
        "activationError": model.activationError,
        "activatedTimeStamp": model.activatedTimeStamp.isoformat() if model.activatedTimeStamp else None,
        "parentFolderUri": model.parentFolderUri,
        "fromRevisionUri": model.fromRevisionUri,
        "version": model.version,
        "members": [],
        "links": generate_group_links(model.id),
    }
    for member in model.members:
        member_data = {
            "id": member.id,
            "definitionId": member.definitionId,
            "definitionRevisionId": member.definitionRevisionId,
            "definitionRevisionName": member.definitionRevisionName,
            "attributeValueMappings": [],
            "attributeNameAliases": [],
        }
        for avm in member.attributeValueMappings:
            member_data["attributeValueMappings"].append({
                "id": avm.id,
                "attributeId": avm.attributeId,
                "attributeName": avm.attributeName,
                "mappingType": avm.mappingType,
                "value": avm.value,
            })
        for ana in member.attributeNameAliases:
            member_data["attributeNameAliases"].append({
                "id": ana.id,
                "attributeId": ana.attributeId,
                "attributeName": ana.attributeName,
                "aliasName": ana.aliasName,
            })
        data["members"].append(member_data)
    return data


def group_model_to_summary(model: TreatmentDefinitionGroup) -> dict:
    return {
        "id": model.id,
        "name": model.name,
        "description": model.description,
        "status": model.status,
        "links": generate_group_links(model.id),
    }


def group_model_to_revision_summary(model: TreatmentDefinitionGroup) -> dict:
    return {
        "id": model.id,
        "name": model.name,
        "majorRevision": model.majorRevision,
        "minorRevision": model.minorRevision,
        "status": model.status,
        "links": generate_group_links(model.id),
    }


async def create_group_members_from_schema(db: AsyncSession, group_id: int, members: list):
    for member_data in members:
        member = GroupMember(
            group_id=group_id,
            definitionId=member_data.definitionId,
            definitionRevisionId=member_data.definitionRevisionId,
            definitionRevisionName=member_data.definitionRevisionName,
        )
        db.add(member)
        await db.flush()

        if member_data.attributeValueMappings:
            for avm_data in member_data.attributeValueMappings:
                avm = AttributeValueMapping(
                    member_id=member.id,
                    attributeId=avm_data.attributeId,
                    attributeName=avm_data.attributeName,
                    mappingType=avm_data.mappingType,
                    value=avm_data.value,
                )
                db.add(avm)

        if member_data.attributeNameAliases:
            for ana_data in member_data.attributeNameAliases:
                ana = AttributeNameAlias(
                    member_id=member.id,
                    attributeId=ana_data.attributeId,
                    attributeName=ana_data.attributeName,
                    aliasName=ana_data.aliasName,
                )
                db.add(ana)


@app.get(
    f"{GROUP_BASE_URI}",
    responses={
        200: {
            "content": {
                MEDIA_TYPE_COLLECTION: {},
                MEDIA_TYPE_SUMMARY: {},
                MEDIA_TYPE_REVISION_SUMMARY: {},
            },
            "description": "Collection of treatment definition groups",
        }
    },
)
async def get_groups(
    request: Request,
    start: int = Query(0, ge=0, description="Start index for pagination"),
    limit: int = Query(10, ge=1, le=100, description="Maximum items to return"),
    filter: Optional[str] = Query(None, description="Filter criteria (e.g., eq(name,'Test'))"),
    sortedBy: Optional[str] = Query(None, description="Sort by field (e.g., -majorRevision, name:ascending)"),
    accept_item: Optional[str] = Header(None, alias="Accept-Item"),
):
    try:
        parsed_filters = parse_filter(filter) if filter else []
    except FilterParseError as e:
        raise HTTPException(status_code=400, detail=str(e))

    async with async_session() as db:
        query = select(TreatmentDefinitionGroup).options(
            selectinload(TreatmentDefinitionGroup.members)
            .selectinload(GroupMember.attributeValueMappings),
            selectinload(TreatmentDefinitionGroup.members)
            .selectinload(GroupMember.attributeNameAliases),
        )

        if filter:
            query = apply_filters(query, parsed_filters, TreatmentDefinitionGroup)

        if sortedBy:
            sort_field, direction = parse_sort_by(sortedBy)
            if sort_field and hasattr(TreatmentDefinitionGroup, sort_field):
                column = getattr(TreatmentDefinitionGroup, sort_field)
                if direction == 'descending':
                    query = query.order_by(column.desc())
                else:
                    query = query.order_by(column)
            else:
                query = query.order_by(TreatmentDefinitionGroup.id)
        else:
            query = query.order_by(TreatmentDefinitionGroup.id)

        count_query = select(func.count()).select_from(TreatmentDefinitionGroup)
        if filter:
            count_query = apply_filters(count_query, parsed_filters, TreatmentDefinitionGroup)
        result = await db.execute(count_query)
        count = result.scalar()

        query = query.offset(start).limit(limit)
        result = await db.execute(query)
        groups = result.scalars().all()

        if accept_item == MEDIA_TYPE_GROUP_REVISION_SUMMARY:
            items = [group_model_to_revision_summary(g) for g in groups]
            media_type = MEDIA_TYPE_GROUP_REVISION_SUMMARY
        elif accept_item == MEDIA_TYPE_GROUP_SUMMARY:
            items = [group_model_to_summary(g) for g in groups]
            media_type = MEDIA_TYPE_GROUP_SUMMARY
        else:
            items = [group_model_to_response(g) for g in groups]
            media_type = MEDIA_TYPE_COLLECTION

        collection = {
            "items": items,
            "start": start,
            "limit": limit,
            "count": count,
            "links": generate_group_collection_links(start, limit, count),
        }

        return JSONResponse(content=collection, media_type=media_type)


@app.get(
    f"{GROUP_BASE_URI}/{{group_id}}",
    responses={
        200: {
            "content": {
                MEDIA_TYPE_GROUP: {},
                MEDIA_TYPE_SUMMARY: {},
                MEDIA_TYPE_REVISION_SUMMARY: {},
            },
            "description": "Treatment definition group",
        },
        404: {"description": "Group not found"},
    },
)
async def get_group(
    group_id: int,
    request: Request,
    view: Optional[str] = Query(None, description="View type: summary or revisionSummary"),
    accept_item: Optional[str] = Header(None, alias="Accept-Item"),
):
    async with async_session() as db:
        query = select(TreatmentDefinitionGroup).options(
            selectinload(TreatmentDefinitionGroup.members)
            .selectinload(GroupMember.attributeValueMappings),
            selectinload(TreatmentDefinitionGroup.members)
            .selectinload(GroupMember.attributeNameAliases),
        ).where(TreatmentDefinitionGroup.id == group_id)
        result = await db.execute(query)
        group = result.scalar_one_or_none()

        if not group:
            raise HTTPException(status_code=404, detail="Group not found")

        url_fragment = request.url.fragment if request.url.fragment else None

        is_summary = (view == "summary") or (url_fragment == "summary")
        is_revision = (view == "revisionSummary") or (url_fragment == "revisionSummary")

        if is_revision or accept_item == MEDIA_TYPE_GROUP_REVISION_SUMMARY:
            data = group_model_to_revision_summary(group)
            media_type = MEDIA_TYPE_GROUP_REVISION_SUMMARY
        elif is_summary or accept_item == MEDIA_TYPE_GROUP_SUMMARY:
            data = group_model_to_summary(group)
            media_type = MEDIA_TYPE_GROUP_SUMMARY
        else:
            data = group_model_to_response(group)
            media_type = MEDIA_TYPE_GROUP

        return JSONResponse(content=data, media_type=media_type)


@app.post(
    f"{GROUP_BASE_URI}",
    status_code=201,
    responses={
        201: {
            "content": {MEDIA_TYPE_GROUP: {}},
            "description": "Created treatment definition group",
        },
        400: {"description": "Invalid input"},
    },
)
async def create_group(
    group: TreatmentDefinitionGroupCreate,
    request: Request,
):
    try:
        async with async_session() as db:
            new_group = TreatmentDefinitionGroup(
                name=group.name,
                description=group.description,
                parentFolderUri=group.parentFolderUri,
                fromRevisionUri=group.fromRevisionUri,
                createdBy="system",
                modifiedBy="system",
            )
            db.add(new_group)
            await db.flush()

            if group.members:
                await create_group_members_from_schema(db, new_group.id, group.members)

            await db.commit()
            group_id = new_group.id
            group_version = new_group.version

        async with async_session() as db:
            query = select(TreatmentDefinitionGroup).options(
                selectinload(TreatmentDefinitionGroup.members)
                .selectinload(GroupMember.attributeValueMappings),
                selectinload(TreatmentDefinitionGroup.members)
                .selectinload(GroupMember.attributeNameAliases),
            ).where(TreatmentDefinitionGroup.id == group_id)
            result = await db.execute(query)
            created = result.scalar_one()

            data = group_model_to_response(created)
            response = JSONResponse(
                content=data,
                status_code=201,
                media_type=MEDIA_TYPE_GROUP,
            )
            response.headers["Location"] = f"{GROUP_BASE_URI}/{created.id}"
            response.headers["ETag"] = str(group_version)
            return response
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=str(e))


@app.put(
    f"{GROUP_BASE_URI}/{{group_id}}",
    responses={
        200: {
            "content": {MEDIA_TYPE_GROUP: {}},
            "description": "Updated treatment definition group",
        },
        400: {"description": "Invalid input"},
        404: {"description": "Group not found"},
        412: {"description": "Precondition failed (ETag mismatch)"},
    },
)
async def update_group(
    group_id: int,
    group: TreatmentDefinitionGroupUpdate,
    request: Request,
    if_match: Optional[str] = Header(None, alias="If-Match"),
):
    try:
        async with async_session() as db:
            query = select(TreatmentDefinitionGroup).options(
                selectinload(TreatmentDefinitionGroup.members)
                .selectinload(GroupMember.attributeValueMappings),
                selectinload(TreatmentDefinitionGroup.members)
                .selectinload(GroupMember.attributeNameAliases),
            ).where(TreatmentDefinitionGroup.id == group_id)
            result = await db.execute(query)
            existing = result.scalar_one_or_none()

            if not existing:
                raise HTTPException(status_code=404, detail="Group not found")

            if if_match and str(existing.version) != if_match:
                raise HTTPException(status_code=412, detail="ETag mismatch")

            if group.name is not None:
                existing.name = group.name
            if group.description is not None:
                existing.description = group.description

            existing.modifiedBy = "system"
            existing.version = existing.version + 1
            existing.minorRevision = existing.minorRevision + 1

            if group.members is not None:
                await db.execute(delete(AttributeNameAlias).where(
                    AttributeNameAlias.member_id.in_(
                        select(GroupMember.id).where(GroupMember.group_id == group_id)
                    )
                ))
                await db.execute(delete(AttributeValueMapping).where(
                    AttributeValueMapping.member_id.in_(
                        select(GroupMember.id).where(GroupMember.group_id == group_id)
                    )
                ))
                await db.execute(delete(GroupMember).where(GroupMember.group_id == group_id))

                await create_group_members_from_schema(db, group_id, group.members)

            await db.commit()
            group_version = existing.version

        async with async_session() as db:
            query = select(TreatmentDefinitionGroup).options(
                selectinload(TreatmentDefinitionGroup.members)
                .selectinload(GroupMember.attributeValueMappings),
                selectinload(TreatmentDefinitionGroup.members)
                .selectinload(GroupMember.attributeNameAliases),
            ).where(TreatmentDefinitionGroup.id == group_id)
            result = await db.execute(query)
            updated = result.scalar_one()

            data = group_model_to_response(updated)
            response = JSONResponse(
                content=data,
                status_code=200,
                media_type=MEDIA_TYPE_GROUP,
            )
            response.headers["ETag"] = str(group_version)
            return response
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=str(e))


@app.delete(
    f"{GROUP_BASE_URI}/{{group_id}}",
    status_code=204,
    responses={
        204: {"description": "Group deleted successfully"},
        404: {"description": "Group not found"},
    },
)
async def delete_group(
    group_id: int,
    request: Request,
):
    try:
        async with async_session() as db:
            query = select(TreatmentDefinitionGroup).where(TreatmentDefinitionGroup.id == group_id)
            result = await db.execute(query)
            existing = result.scalar_one_or_none()

            if not existing:
                raise HTTPException(status_code=404, detail="Group not found")

            await db.execute(delete(AttributeNameAlias).where(
                AttributeNameAlias.member_id.in_(
                    select(GroupMember.id).where(GroupMember.group_id == group_id)
                )
            ))
            await db.execute(delete(AttributeValueMapping).where(
                AttributeValueMapping.member_id.in_(
                    select(GroupMember.id).where(GroupMember.group_id == group_id)
                )
            ))
            await db.execute(delete(GroupMember).where(GroupMember.group_id == group_id))
            await db.delete(existing)
            await db.commit()

            return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=str(e))


@app.get(
    f"{GROUP_BASE_URI}/{{group_id}}/dependencies",
    responses={
        200: {
            "content": {MEDIA_TYPE_COLLECTION: {}},
            "description": "Direct dependencies of the group",
        },
        404: {"description": "Group not found"},
    },
)
async def get_group_dependencies(
    group_id: int,
    request: Request,
):
    async with async_session() as db:
        query = select(TreatmentDefinitionGroup).where(TreatmentDefinitionGroup.id == group_id)
        result = await db.execute(query)
        group = result.scalar_one_or_none()

        if not group:
            raise HTTPException(status_code=404, detail="Group not found")

        collection = {
            "items": [],
            "start": 0,
            "limit": 0,
            "count": 0,
            "links": [
                link_to_dict(Link(rel="self", href=f"{GROUP_BASE_URI}/{group_id}/dependencies", method="GET", type=MEDIA_TYPE_COLLECTION)),
                link_to_dict(Link(rel="up", href=f"{GROUP_BASE_URI}/{group_id}", method="GET", type=MEDIA_TYPE_GROUP)),
            ],
        }

        return JSONResponse(content=collection, media_type=MEDIA_TYPE_COLLECTION)
