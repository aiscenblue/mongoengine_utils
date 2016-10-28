#!/usr/bin/env python
# coding=utf-8

"""Documents implementing human-readable JSON serializer."""

import json

try:
    from functools import singledispatch
except ImportError:
    from singledispatch import singledispatch

import mongoengine as db
from bson import SON, DBRef
from .encoder import GoodJSONEncoder
from .decoder import generate_object_hook
from .queryset import QuerySet


class Helper(object):
    """Helper class to serialize / deserialize JSON document."""

    def _follow_reference(self, max_depth, current_depth,
                          use_db_field, *args, **kwargs):
        from .fields import FollowReferenceField
        ret = {}
        for fldname in self:
            fld = self._fields.get(fldname)
            is_list = isinstance(fld, db.ListField)
            target = fld.field if is_list else fld

            if all([
                isinstance(
                    target, (db.ReferenceField, db.EmbeddedDocumentField)
                ), not isinstance(target, FollowReferenceField)
            ]):
                value = None
                if is_list:
                    value = []
                    for doc in getattr(self, fldname, []):
                        value.append(json.loads((
                            target.document_type.objects(
                                id=doc.id
                            ).get() if isinstance(doc, DBRef) else doc
                        ).to_json(
                            follow_reference=True,
                            max_depth=max_depth,
                            current_depth=current_depth + 1,
                            use_db_field=use_db_field,
                            *args, **kwargs
                        )))
                else:
                    doc = getattr(self, fldname, None)
                    value = json.loads(
                        (
                            target.document_type.objects(
                                id=doc.id
                            ).get() if isinstance(doc, DBRef) else doc
                        ).to_json(
                            follow_reference=True,
                            max_depth=max_depth,
                            current_depth=current_depth + 1,
                            use_db_field=use_db_field,
                            *args, **kwargs
                        )
                    ) if doc else doc
                if value is not None:
                    ret.update({fldname: value})
        return ret

    def __set_gj_flag_sub_field(self, instance, fld, cur_depth):
        """Set $$good_json$$ flag to subfield."""
        from mongoengine_goodjson.fields import FollowReferenceField

        def set_good_json(fld):
            setattr(fld, "$$good_json$$", True)
            setattr(fld, "$$cur_depth$$", cur_depth)

        @singledispatch
        def set_flag_recursive(fld, instance):
            set_good_json(fld)

        @set_flag_recursive.register(db.ListField)
        def set_flag_list(fld, instance):
            set_good_json(fld.field)

        @set_flag_recursive.register(db.EmbeddedDocumentField)
        def set_flag_emb(fld, instance):
            if isinstance(instance, Helper):
                instance.begin_goodjson(cur_depth)

        @set_flag_recursive.register(FollowReferenceField)
        def set_flag_self(fld, instance):
            set_good_json(fld)

        set_flag_recursive(fld, instance)

    def __unset_gj_flag_sub_field(self, instance, fld, cur_depth):
        """Unset $$good_json$$ to subfield."""
        from mongoengine_goodjson.fields import FollowReferenceField

        def unset_flag(fld):
            setattr(fld, "$$good_json$$", None)
            setattr(fld, "$$cur_depth$$", None)
            delattr(fld, "$$good_json$$")
            delattr(fld, "$$cur_depth$$")

        @singledispatch
        def unset_flag_recursive(fld, instance):
            unset_flag(fld)

        @unset_flag_recursive.register(db.ListField)
        def unset_flag_list(fld, instance):
            unset_flag(fld.field)

        @unset_flag_recursive.register(db.EmbeddedDocumentField)
        def unset_flag_emb(fld, instance):
            if isinstance(instance, Helper):
                instance.end_goodjson(cur_depth)

        @unset_flag_recursive.register(FollowReferenceField)
        def unset_flag_self(fld, instance):
            unset_flag(fld)

        unset_flag_recursive(fld, instance)

    def begin_goodjson(self, cur_depth=0):
        """Enable GoodJSON Flag."""
        for (name, fld) in self._fields.items():
            self.__set_gj_flag_sub_field(
                getattr(self, name), fld, cur_depth=cur_depth
            )

    def end_goodjson(self, cur_depth=0):
        """Stop GoodJSON Flag."""
        for (name, fld) in self._fields.items():
            self.__unset_gj_flag_sub_field(
                getattr(self, name), fld, cur_depth=cur_depth
            )

    def to_mongo(self, *args, **kwargs):
        """Convert into mongodb compatible dict."""
        result = super(Helper, self).to_mongo(*args, **kwargs)
        return result

    def to_json(self, *args, **kwargs):
        """
        Encode to human-readable json.

        Parameters:
            use_db_field: use_db_field that is passed to to_mongo.
            follow_reference: set True to follow reference field.
            max_depth: maximum recursion depth. If this value is set to None,
                the reference is followed until it is end. Setting 0 is the
                same meaning of follow_reference=0.
                By default, the value is 3.
            current_depth: This is used internally to identify current
                recursion depth. Therefore, you should leave this value as-is.
                By default, the value is 0.
            *args, **kwargs: Any arguments, keyword arguments to
                tell json.dumps.
        """
        use_db_field = kwargs.pop('use_db_field', True)
        follow_reference = kwargs.pop("follow_reference", False)
        max_depth = kwargs.pop("max_depth", 3)
        current_depth = kwargs.pop("current_depth", 0)

        if "cls" not in kwargs:
            kwargs["cls"] = GoodJSONEncoder

        self.begin_goodjson()

        data = self.to_mongo(use_db_field)
        if "_id" in data and "id" not in data:
            data["id"] = data.pop("_id", None)

        for name, fld in self._fields.items():
            if any([
                getattr(fld, "exclude_to_json", None),
                getattr(fld, "exclude_json", None)
            ]):
                data.pop(name, None)

        if follow_reference and \
                (current_depth < max_depth or max_depth is None):
            data.update(self._follow_reference(
                max_depth, current_depth, use_db_field, *args, **kwargs
            ))

        self.end_goodjson()

        return json.dumps(data, *args, **kwargs)

    @classmethod
    def from_json(cls, json_str, created=False, *args, **kwargs):
        """
        Decode from human-readable json.

        Parameters:
            json_str: JSON string that should be passed to the serialized
            created: a parameter that is passed to cls._from_son.
            *args, **kwargs: Any additional arguments that is passed to
                json.loads.
        """
        from .fields import FollowReferenceField
        hook = generate_object_hook(cls)
        if "object_hook" not in kwargs:
            kwargs["object_hook"] = hook
        dct = json.loads(json_str, *args, **kwargs)
        for name, fld in cls._fields.items():
            if any([
                getattr(fld, "exclude_from_json", None),
                getattr(fld, "exclude_json", None)
            ]):
                dct.pop(name, None)
        from_son_result = cls._from_son(SON(dct), created=created)

        @singledispatch
        def normalize_reference(ref_id, fld):
            """Normalize Reference."""
            return ref_id and fld.to_python(ref_id) or None

        @normalize_reference.register(dict)
        def normalize_reference_dict(ref_id, fld):
            """Normalize Reference for dict."""
            return fld.to_python(ref_id["id"])

        @normalize_reference.register(list)
        def normalize_reference_list(ref_id, fld):
            """Normalize Reference for list."""
            return [
                normalize_reference(ref.id, fld) for ref in ref_id
            ]

        for fldname, fld in cls._fields.items():
            target = fld.field if isinstance(fld, db.ListField) else fld

            if not isinstance(target, db.ReferenceField) or \
                    isinstance(target, FollowReferenceField):
                continue

            value = dct.get(fldname)
            setattr(
                from_son_result, fldname,
                normalize_reference(getattr(value, "id", value), target)
            )
        return from_son_result


class Document(Helper, db.Document):
    """Document implementing human-readable JSON serializer."""

    meta = {
        "abstract": True,
        "queryset_class": QuerySet
    }


class EmbeddedDocument(Helper, db.EmbeddedDocument):
    """EmbeddedDocument implementing human-readable JSON serializer."""

    meta = {
        "abstract": True,
        "queryset_class": QuerySet
    }

class MongoEnginePaginationException(Exception):
    pass


class BaseQuerySet(QuerySet):
    """
    A base queryset with handy extras
    """

    #def get_or_404(self, *args, **kwargs):
        #try:
            #return self.get(*args, **kwargs)
        #except (MultipleObjectsReturned, DoesNotExist, ValidationError):
            #raise MongoEnginePaginationException()

    #def first_or_404(self):

        #obj = self.first()
        #if obj is None:
            #raise MongoEnginePaginationException()

        #return obj

    def paginate(self, page, per_page, error_out=True):

        return Pagination(self, page, per_page)

    def paginate_field(self, field_name, doc_id, page, per_page,
            total=None):
        item = self.get(id=doc_id)
        count = getattr(item, field_name + "_count", '')
        total = total or count or len(getattr(item, field_name))
        return ListFieldPagination(self, field_name, doc_id, page, per_page,
            total=total)


class Pagination(object):

    def __init__(self, iterable, page, per_page):

        if page < 1:
            raise MongoEnginePaginationException()

        self.iterable = iterable
        self.page = page
        self.per_page = per_page
        self.total = len(iterable)

        start_index = (page - 1) * per_page
        end_index = page * per_page

        self.items = iterable[start_index:end_index]
        if isinstance(self.items, QuerySet):
            self.items = self.items.select_related()
        if not self.items and page != 1:
            raise MongoEnginePaginationException()

    @property
    def pages(self):
        """The total number of pages"""
        return int(math.ceil(self.total / float(self.per_page)))

    def prev(self, error_out=False):
        """Returns a :class:`Pagination` object for the previous page."""
        assert self.iterable is not None, 'an object is required ' \
                                       'for this method to work'
        iterable = self.iterable
        if isinstance(iterable, QuerySet):
            iterable._skip = None
            iterable._limit = None
            iterable = iterable.clone()
        return self.__class__(iterable, self.page - 1, self.per_page)

    @property
    def prev_num(self):
        """Number of the previous page."""
        return self.page - 1

    @property
    def has_prev(self):
        """True if a previous page exists"""
        return self.page > 1

    def next(self, error_out=False):
        """Returns a :class:`Pagination` object for the next page."""
        assert self.iterable is not None, 'an object is required ' \
                                       'for this method to work'
        iterable = self.iterable
        if isinstance(iterable, QuerySet):
            iterable._skip = None
            iterable._limit = None
            iterable = iterable.clone()
        return self.__class__(iterable, self.page + 1, self.per_page)

    @property
    def has_next(self):
        """True if a next page exists."""
        return self.page < self.pages

    @property
    def next_num(self):
        """Number of the next page"""
        return self.page + 1

    def iter_pages(self, left_edge=2, left_current=2,
                   right_current=3, right_edge=2):
        """Iterates over the page numbers in the pagination.  The four
        parameters control the thresholds how many numbers should be produced
        from the sides.  Skipped page numbers are represented as `None`.
        This is how you could render such a pagination in the templates:
        .. sourcecode:: html+jinja
            {% macro render_pagination(pagination, endpoint) %}
              <div class=pagination>
              {%- for page in pagination.iter_pages() %}
                {% if page %}
                  {% if page != pagination.page %}
                    <a href="{{ url_for(endpoint, page=page) }}">{{ page }}</a>
                  {% else %}
                    <strong>{{ page }}</strong>
                  {% endif %}
                {% else %}
                  <span class=ellipsis>…</span>
                {% endif %}
              {%- endfor %}
              </div>
            {% endmacro %}
        """
        last = 0
        for num in xrange(1, self.pages + 1):
            if num <= left_edge or \
               (num > self.page - left_current - 1 and
                num < self.page + right_current) or \
               num > self.pages - right_edge:
                if last + 1 != num:
                    yield None
                yield num
                last = num


class ListFieldPagination(Pagination):

    def __init__(self, queryset, field_name, doc_id, page, per_page,
                 total=None):
        """Allows an array within a document to be paginated.
        Queryset must contain the document which has the array we're
        paginating, and doc_id should be it's _id.
        Field name is the name of the array we're paginating.
        Page and per_page work just like in Pagination.
        Total is an argument because it can be computed more efficiently
        elsewhere, but we still use array.length as a fallback.
        """
        if page < 1:
            raise MongoEnginePaginationException()

        self.page = page
        self.per_page = per_page

        self.queryset = queryset
        self.doc_id = doc_id
        self.field_name = field_name

        start_index = (page - 1) * per_page

        field_attrs = {field_name: {"$slice": [start_index, per_page]}}

        self.items = getattr(queryset().fields(**field_attrs
            ).first(), field_name)

        self.total = total or len(self.items)

        if not self.items and page != 1:
            raise MongoEnginePaginationException()

    def prev(self, error_out=False):
        """Returns a :class:`Pagination` object for the previous page."""
        assert self.items is not None, 'a query object is required ' \
                                       'for this method to work'
        return self.__class__(self.queryset, self.doc_id, self.field_name,
            self.page - 1, self.per_page, self.total)

    def next(self, error_out=False):
        """Returns a :class:`Pagination` object for the next page."""
        assert self.iterable is not None, 'a query object is required ' \
                                       'for this method to work'
        return self.__class__(self.queryset, self.doc_id, self.field_name,
            self.page + 1, self.per_page, self.total)
