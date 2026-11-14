"""This file and its contents are licensed under the Apache License 2.0. Please see the included NOTICE for copyright information and LICENSE for a copy of the license."""

import logging
from collections import OrderedDict
from typing import Any, Iterable, Tuple
from urllib.parse import unquote

import ujson as json
from core.utils.common import int_from_request, load_func
from data_manager.models import View
from data_manager.prepare_params import PrepareParams
from django.conf import settings
from django.db import connection
from django.db.models import BooleanField, Exists, OuterRef, Q
from django.db.models.expressions import RawSQL
from django.db.models.query import QuerySet
from rest_framework.exceptions import ValidationError
from rest_framework.generics import get_object_or_404
from tasks.models import Task

TASKS = 'tasks:'
DEFECT_CONTROL_NAME = 'defect_mask'
DEFECT_FILTER_COLUMN_ID = 'annotations_results_json.defect_mask'
logger = logging.getLogger(__name__)


class DataManagerException(Exception):
    pass


def noop_validate_column_access(project, user, column_refs=None, payload=None, message=None):
    """OSS no-op for DATA_MANAGER_VALIDATE_COLUMN_ACCESS."""
    return None


def run_column_access_validation(project, user, *, payload=None, column_refs=None, message=None):
    path = getattr(settings, 'DATA_MANAGER_VALIDATE_COLUMN_ACCESS', None)
    if not path:
        return
    load_func(path)(project, user, column_refs=column_refs, payload=payload, message=message)


def noop_sanitize_column_ordering(project, user, ordering):
    """OSS no-op for DATA_MANAGER_SANITIZE_COLUMN_ORDERING."""
    return ordering


def run_column_ordering_sanitize(project, user, ordering):
    path = getattr(settings, 'DATA_MANAGER_SANITIZE_COLUMN_ORDERING', None)
    if not path:
        return ordering
    return load_func(path)(project, user, ordering)


def get_all_columns(project, *_):
    """Make columns info for the frontend data manager"""
    result = {'columns': []}

    # frontend uses MST data model, so we need two directional referencing parent <-> child
    task_data_children = []
    i = 0

    data_types = OrderedDict()

    # add data types from config again
    project_data_types = {}
    for key, value in project.data_types.items():
        # skip keys from Repeater tag, because we already have its base data,
        # e.g.: skip 'image[{{idx}}]' because we have 'image' list already
        if '[' not in key:
            project_data_types[key] = value
    data_types.update(project_data_types.items())

    # all data types from import data
    all_data_columns = project.summary.all_data_columns
    # Lazy %s args: avoid formatting large column dicts when DEBUG is disabled
    logger.debug(
        'get_all_columns: project_id=%s all_data_columns=%s data_types=%s', project.id, all_data_columns, data_types
    )
    if all_data_columns:
        data_types.update({key: 'Unknown' for key in all_data_columns if key not in data_types})
    logger.debug('get_all_columns: project_id=%s data_types=%s', project.id, data_types)

    # remove $undefined$ if there is one type at least in labeling config, because it will be resolved automatically
    if len(project_data_types) > 0:
        data_types.pop(settings.DATA_UNDEFINED_NAME, None)
    logger.debug(
        'get_all_columns: project_id=%s data_types=%s project_data_types=%s',
        project.id,
        data_types,
        project_data_types,
    )

    for key, data_type in list(data_types.items()):  # make data types from labeling config first
        column = {
            'id': key,
            'title': key if key != settings.DATA_UNDEFINED_NAME else 'data',
            'type': data_type if data_type in ['Image', 'Audio', 'AudioPlus', 'Video', 'Unknown'] else 'String',
            'target': 'tasks',
            'parent': 'data',
            'visibility_defaults': {
                'explore': True,
                'labeling': key in project_data_types or key == settings.DATA_UNDEFINED_NAME,
            },
            'project_defined': True,
        }
        result['columns'].append(column)
        task_data_children.append(column['id'])
        i += 1

    # --- Data root ---
    data_root = {
        'id': 'data',
        'title': 'data',
        'type': 'List',
        'target': 'tasks',
        'children': task_data_children,
        'project_defined': False,
    }

    result['columns'] += [
        # --- Tasks ---
        {
            'id': 'id',
            'title': 'ID',
            'type': 'Number',
            'help': 'Task ID',
            'target': 'tasks',
            'visibility_defaults': {'explore': True, 'labeling': False},
            'project_defined': False,
        }
    ]

    result['columns'] += [
        {
            'id': 'inner_id',
            'title': 'Inner ID',
            'type': 'Number',
            'help': 'Internal task ID starting from 1 for the current project',
            'target': 'tasks',
            'visibility_defaults': {'explore': False, 'labeling': False},
            'project_defined': False,
        }
    ]

    result['columns'] += [
        {
            'id': 'completed_at',
            'title': 'Completed',
            'type': 'Datetime',
            'target': 'tasks',
            'help': 'Latest annotation time, set once the task has all required annotations',
            'visibility_defaults': {'explore': True, 'labeling': False},
            'project_defined': False,
        },
        {
            'id': 'total_annotations',
            'title': 'Annotations',
            'type': 'Number',
            'target': 'tasks',
            'help': 'Total annotations per task',
            'visibility_defaults': {'explore': True, 'labeling': True},
            'project_defined': False,
        },
        {
            'id': 'cancelled_annotations',
            'title': 'Cancelled',
            'type': 'Number',
            'target': 'tasks',
            'help': 'Total cancelled (skipped) annotations',
            'visibility_defaults': {'explore': True, 'labeling': False},
            'project_defined': False,
        },
        {
            'id': 'total_predictions',
            'title': 'Predictions',
            'type': 'Number',
            'target': 'tasks',
            'help': 'Total predictions per task',
            'visibility_defaults': {'explore': True, 'labeling': False},
            'project_defined': False,
        },
        {
            'id': 'annotators',
            'title': 'Annotated by',
            'type': 'List',
            'target': 'tasks',
            'help': 'All users who completed the task',
            'schema': {'multiple': True},
            'visibility_defaults': {'explore': True, 'labeling': False},
            'project_defined': False,
        },
        {
            'id': 'annotations_results',
            'title': 'Annotation results',
            'type': 'String',
            'target': 'tasks',
            'help': 'Annotation results stacked over all annotations',
            'visibility_defaults': {'explore': False, 'labeling': False},
            'project_defined': False,
        },
        {
            'id': 'annotations_ids',
            'title': 'Annotation IDs',
            'type': 'String',
            'target': 'tasks',
            'help': 'Annotation IDs stacked over all annotations',
            'visibility_defaults': {'explore': False, 'labeling': False},
            'project_defined': False,
        },
        {
            'id': 'predictions_score',
            'title': 'Prediction score',
            'type': 'Number',
            'target': 'tasks',
            'help': 'Average prediction score over all task predictions',
            'visibility_defaults': {'explore': False, 'labeling': False},
            'project_defined': False,
        },
        {
            'id': 'predictions_model_versions',
            'title': 'Prediction model versions',
            'type': 'List',
            'target': 'tasks',
            'help': 'Model versions aggregated over all predictions',
            'schema': {'items': project.get_model_versions(), 'multiple': True},
            'visibility_defaults': {'explore': False, 'labeling': False},
            'project_defined': False,
        },
        {
            'id': 'predictions_results',
            'title': 'Prediction results',
            'type': 'String',
            'target': 'tasks',
            'help': 'Prediction results stacked over all predictions',
            'visibility_defaults': {'explore': False, 'labeling': False},
            'project_defined': False,
        },
        {
            'id': 'file_upload',
            'title': 'Upload filename',
            'type': 'String',
            'target': 'tasks',
            'help': 'Filename of uploaded file',
            'visibility_defaults': {'explore': False, 'labeling': False},
            'project_defined': False,
        },
        {
            'id': 'storage_filename',
            'title': 'Storage filename',
            'type': 'String',
            'target': 'tasks',
            'help': 'Filename from import storage',
            'visibility_defaults': {'explore': False, 'labeling': False},
            'project_defined': False,
        },
        {
            'id': 'created_at',
            'title': 'Created at',
            'type': 'Datetime',
            'target': 'tasks',
            'help': 'Task creation time',
            'visibility_defaults': {'explore': False, 'labeling': False},
            'project_defined': False,
        },
        {
            'id': 'updated_at',
            'title': 'Updated at',
            'type': 'Datetime',
            'target': 'tasks',
            'help': 'Task update time',
            'visibility_defaults': {'explore': False, 'labeling': False},
            'project_defined': False,
        },
        {
            'id': 'updated_by',
            'title': 'Updated by',
            'type': 'List',
            'target': 'tasks',
            'help': 'User who did the last task update',
            'schema': {'multiple': True},
            'visibility_defaults': {'explore': False, 'labeling': False},
            'project_defined': False,
        },
        {
            'id': 'avg_lead_time',
            'title': 'Lead Time',
            'type': 'Time',
            'help': 'Average lead time over all annotations',
            'target': 'tasks',
            'visibility_defaults': {'explore': False, 'labeling': False},
            'project_defined': False,
        },
        {
            'id': 'draft_exists',
            'title': 'Drafts',
            'type': 'Boolean',
            'help': 'True if at least one draft exists for the task',
            'target': 'tasks',
            'visibility_defaults': {'explore': False, 'labeling': False},
            'project_defined': False,
        },
    ]

    result['columns'].append(data_root)

    # ``defect_mask`` is an annotation-result filter, rather than a task.data
    # field.  Keep it filter-only so it can be selected in Data Manager without
    # pretending that the value is stored on Task.
    parsed_config = project.get_parsed_config()
    defect_config = parsed_config.get(DEFECT_CONTROL_NAME, {}) if parsed_config else {}
    if defect_config.get('type') == 'BrushLabels':
        labels = defect_config.get('labels', [])
        result['columns'].append(
            {
                'id': DEFECT_FILTER_COLUMN_ID,
                'title': '缺陷类型',
                'type': 'List',
                'target': 'tasks',
                'help': 'Submitted defect labels from the defect_mask annotations',
                'schema': {
                    'items': [{'value': label, 'title': label} for label in labels],
                    'multiple': False,
                },
                'visibility_defaults': {'explore': False, 'labeling': False},
                'project_defined': False,
            }
        )

    return result


def get_prepare_params(request, project):
    """This function extract prepare_params from
    * view_id if it's inside of request data
    * selectedItems, filters, ordering if they are in request and there is no view id
    """
    # use filters and selected items from view
    view_id = int_from_request(request.GET, 'view', 0) or int_from_request(request.data, 'view', 0)
    if view_id > 0:
        view = get_object_or_404(View, pk=view_id)
        if view.project.pk != project.pk:
            raise ValidationError('Project and View mismatch')
        prepare_params = view.get_prepare_tasks_params(add_selected_items=True)
        prepare_params.request = request

    # use filters and selected items from request if it's specified
    else:
        # query arguments from url
        if 'query' in request.GET:
            data = json.loads(unquote(request.GET['query']))
        # data payload from body
        else:
            data = request.data

        selected = data.get('selectedItems', {'all': True, 'excluded': []})
        if not isinstance(selected, dict):
            if isinstance(selected, str):
                # try to parse JSON string
                try:
                    selected = json.loads(selected)
                except Exception as e:
                    logger.error(f'Error parsing selectedItems: {e}')
                    raise DataManagerException(
                        'selectedItems must be JSON encoded string for dict: {"all": [true|false], '
                        '"excluded | included": [...task_ids...]}. '
                        f'Found: {selected}'
                    )
            else:
                raise DataManagerException(
                    'selectedItems must be dict: {"all": [true|false], '
                    '"excluded | included": [...task_ids...]}. '
                    f'Found type: {type(selected)} with value: {selected}'
                )
        filters = data.get('filters', None)
        ordering = data.get('ordering', [])
        prepare_params = PrepareParams(
            project=project.id, selectedItems=selected, data=data, filters=filters, ordering=ordering, request=request
        )
    # Denied-column filters still apply on reads (shared tabs / reviewers). View save
    # continues to reject them via ViewSerializer. Ordering is stripped for the request only.
    user = getattr(request, 'user', None)
    prepare_params.ordering = run_column_ordering_sanitize(project, user, prepare_params.ordering) or []
    return prepare_params


def get_prepared_queryset(request, project):
    prepare_params = get_prepare_params(request, project)
    queryset = Task.prepared.only_filtered(prepare_params=prepare_params)
    return queryset


def evaluate_predictions(tasks):
    """
    Call the given ML backend to retrieve predictions with the task queryset as an input.
    If backend is not specified, we'll assume the tasks' project only has one associated
    ML backend, and use that backend.
    """
    if not tasks:
        return

    project = tasks[0].project

    backend = project.ml_backend

    if backend:
        return backend.predict_tasks(tasks=tasks)


def filters_ordering_selected_items_exist(data):
    return data.get('filters') or data.get('ordering') or data.get('selectedItems')


def _defect_annotation_queryset(project: Any, label: str) -> QuerySet:
    """Return submitted, non-cancelled annotations containing one defect label."""
    from tasks.models import Annotation

    annotations = Annotation.objects.filter(
        project=project,
        task=OuterRef('pk'),
        completed_by__isnull=False,
        was_cancelled=False,
    )
    if connection.vendor == 'sqlite':
        # SQLite does not implement Django's JSONField ``contains`` lookup.
        # JSON1 lets us inspect each result region while retaining an EXISTS
        # predicate and avoiding a Python-side scan of the task list.
        annotations = annotations.annotate(
            _has_defect=RawSQL(
                """
                EXISTS (
                    SELECT 1
                    FROM json_each(result) AS region
                    WHERE json_extract(region.value, '$.from_name') = %s
                      AND EXISTS (
                          SELECT 1
                          FROM json_each(json_extract(region.value, '$.value.brushlabels')) AS label
                          WHERE label.value = %s
                      )
                )
                """,
                [DEFECT_CONTROL_NAME, label],
                output_field=BooleanField(),
            )
        ).filter(_has_defect=True)
    else:
        annotations = annotations.filter(
            result__contains=[{'from_name': DEFECT_CONTROL_NAME, 'value': {'brushlabels': [label]}}]
        )
    return annotations


def custom_filter_expressions(_filter: Any, field_name: str, project: Any, **kwargs: Any) -> Q | None:
    """Compile the dynamic BrushLabels defect filter into a correlated EXISTS."""
    if field_name != DEFECT_FILTER_COLUMN_ID:
        return None

    control_name = DEFECT_CONTROL_NAME
    parsed_config = project.get_parsed_config() or {}
    control = parsed_config.get(control_name, {})
    configured_labels = set(control.get('labels', [])) if control.get('type') == 'BrushLabels' else set()
    # The catalog declares a single-select value.  Reject arrays and other
    # forged shapes instead of silently using the first element.
    label = _filter.value
    if not isinstance(label, str):
        return Q(pk__in=[])

    # A stale or forged label must fail closed.  This also keeps an old saved
    # View from silently changing meaning after the project config changes.
    if control_name != DEFECT_CONTROL_NAME or label not in configured_labels:
        return Q(pk__in=[])

    expression = Exists(_defect_annotation_queryset(project, label))
    if _filter.operator in ('not_contains', 'not_equal'):
        return ~expression
    if _filter.operator in ('contains', 'equal'):
        return expression
    return Q(pk__in=[])


def preprocess_filter(_filter, *_):
    return _filter


def preprocess_field_name(raw_field_name, project) -> Tuple[str, bool]:
    """Transform a field name (as specified in the datamanager views endpoint) to
    a django ORM field name. Also handle dotted accesses to task.data.

    Edit with care; it's critical that this function not be changed in ways that
    introduce vulnerabilities in the vein of the ORM Leak (see #5012). In particular
    it is not advisable to use `replace` or other calls that replace all instances
    of a string within this function.

    Returns: Django ORM field name: str, Sort is ascending: bool
    """

    field_name = raw_field_name
    ascending = True

    # Descending marker `-` may come at the beginning of the string
    if field_name.startswith('-'):
        ascending = False
        field_name = field_name[1:]

    # For security reasons, these must only be removed when they fall at the beginning of the string (or after `-`).
    optional_prefixes = ['filter:', 'tasks:']
    for prefix in optional_prefixes:
        if field_name.startswith(prefix):
            field_name = field_name[len(prefix) :]

    # Descending marker may also come after other prefixes. Double negative is not allowed.
    if ascending and field_name.startswith('-'):
        ascending = False
        field_name = field_name[1:]

    if field_name.startswith('data.'):
        # process as $undefined$ only if real_name is from labeling config, not from task.data
        real_name = field_name.replace('data.', '')
        common_data_columns = project.summary.common_data_columns
        real_name_suitable = (
            # there is only one object tag in labeling config
            # and requested filter name == value from object tag
            len(project.data_types.keys()) == 1
            and real_name in project.data_types.keys()
            # file was uploaded before labeling config is set, `data.data` is system predefined name
            or len(project.data_types.keys()) == 0
            and real_name == 'data'
        )
        if (
            real_name_suitable
            # common data columns are not None
            and common_data_columns
            # $undefined$ is in common data columns, in all tasks
            and settings.DATA_UNDEFINED_NAME in common_data_columns
        ):
            field_name = f'data__{settings.DATA_UNDEFINED_NAME}'
        else:
            field_name = field_name.replace('data.', 'data__')
    return field_name, ascending


def intersperse(items: Iterable, separator: Any) -> list:
    """
    Create a list with a separator between each item in the passed iterable `items`

    for example, intersperse(['one', 'two', 'three'], 0) == ['one', 0, 'two', 0, 'three']
    """

    output = []
    for item in items:
        output.append(item)
        output.append(separator)
    # if there are no items, there will be no last separator to remove
    if output:
        output.pop()
    return output
