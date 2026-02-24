"""Tests for field auto-classification."""

from django_graph_walker.discovery import FieldClass, classify_field, get_model_fields
from tests.testapp.models import (
    Article,
    ArticleStats,
    Author,
    Category,
    Comment,
    Tag,
)


class TestClassifyField:
    """classify_field should return the correct FieldClass for each Django field type."""

    def _get_field(self, model, name):
        """Get a field object by name from a model."""
        for field in model._meta.get_fields():
            accessor = (
                field.get_accessor_name() if hasattr(field, "get_accessor_name") else field.name
            )
            if accessor == name:
                return field
        raise ValueError(f"No field {name!r} on {model.__name__}")

    def test_auto_field_is_pk(self):
        field = self._get_field(Author, "id")
        result = classify_field(field, in_scope={Author})
        assert result == FieldClass.PK

    def test_char_field_is_value(self):
        field = self._get_field(Author, "name")
        result = classify_field(field, in_scope={Author})
        assert result == FieldClass.VALUE

    def test_email_field_is_value(self):
        field = self._get_field(Author, "email")
        result = classify_field(field, in_scope={Author})
        assert result == FieldClass.VALUE

    def test_text_field_is_value(self):
        field = self._get_field(Article, "body")
        result = classify_field(field, in_scope={Article})
        assert result == FieldClass.VALUE

    def test_boolean_field_is_value(self):
        field = self._get_field(Article, "published")
        result = classify_field(field, in_scope={Article})
        assert result == FieldClass.VALUE

    def test_datetime_auto_field_is_value(self):
        field = self._get_field(Article, "created_at")
        result = classify_field(field, in_scope={Article})
        assert result == FieldClass.VALUE

    def test_fk_to_in_scope_model(self):
        field = self._get_field(Article, "author")
        result = classify_field(field, in_scope={Article, Author})
        assert result == FieldClass.FK_IN_SCOPE

    def test_fk_to_out_of_scope_model(self):
        field = self._get_field(Article, "author")
        result = classify_field(field, in_scope={Article})
        assert result == FieldClass.FK_OUT_OF_SCOPE

    def test_nullable_fk_to_out_of_scope(self):
        field = self._get_field(Article, "reviewer")
        result = classify_field(field, in_scope={Article})
        assert result == FieldClass.FK_OUT_OF_SCOPE

    def test_self_referential_fk_in_scope(self):
        field = self._get_field(Category, "parent")
        result = classify_field(field, in_scope={Category})
        assert result == FieldClass.FK_IN_SCOPE

    def test_m2m_to_in_scope_model(self):
        field = self._get_field(Article, "tags")
        result = classify_field(field, in_scope={Article, Tag})
        assert result == FieldClass.M2M_IN_SCOPE

    def test_m2m_to_out_of_scope_model(self):
        field = self._get_field(Article, "tags")
        result = classify_field(field, in_scope={Article})
        assert result == FieldClass.M2M_OUT_OF_SCOPE

    def test_reverse_fk_from_in_scope(self):
        # Author.articles is a reverse FK from Article (which is in scope)
        field = self._get_field(Author, "articles")
        result = classify_field(field, in_scope={Author, Article})
        assert result == FieldClass.REVERSE_FK_IN_SCOPE

    def test_reverse_fk_from_out_of_scope(self):
        field = self._get_field(Author, "articles")
        result = classify_field(field, in_scope={Author})
        assert result == FieldClass.REVERSE_FK_OUT_OF_SCOPE

    def test_reverse_m2m_from_in_scope(self):
        # Tag.articles is a reverse M2M from Article
        field = self._get_field(Tag, "articles")
        result = classify_field(field, in_scope={Tag, Article})
        assert result == FieldClass.REVERSE_M2M_IN_SCOPE

    def test_reverse_m2m_from_out_of_scope(self):
        field = self._get_field(Tag, "articles")
        result = classify_field(field, in_scope={Tag})
        assert result == FieldClass.REVERSE_M2M_OUT_OF_SCOPE

    def test_one_to_one_field_in_scope(self):
        field = self._get_field(ArticleStats, "article")
        result = classify_field(field, in_scope={ArticleStats, Article})
        assert result == FieldClass.O2O_IN_SCOPE

    def test_one_to_one_field_out_of_scope(self):
        field = self._get_field(ArticleStats, "article")
        result = classify_field(field, in_scope={ArticleStats})
        assert result == FieldClass.O2O_OUT_OF_SCOPE

    def test_reverse_one_to_one_in_scope(self):
        # Article.stats is a reverse OneToOneRel
        field = self._get_field(Article, "stats")
        result = classify_field(field, in_scope={Article, ArticleStats})
        assert result == FieldClass.REVERSE_O2O_IN_SCOPE

    def test_reverse_one_to_one_out_of_scope(self):
        field = self._get_field(Article, "stats")
        result = classify_field(field, in_scope={Article})
        assert result == FieldClass.REVERSE_O2O_OUT_OF_SCOPE

    def test_generic_relation_in_scope(self):
        field = self._get_field(Article, "comments")
        result = classify_field(field, in_scope={Article, Comment})
        assert result == FieldClass.GENERIC_RELATION_IN_SCOPE

    def test_generic_relation_out_of_scope(self):
        field = self._get_field(Article, "comments")
        result = classify_field(field, in_scope={Article})
        assert result == FieldClass.GENERIC_RELATION_OUT_OF_SCOPE

    def test_generic_fk_components_are_value(self):
        """content_type and object_id on GenericFK models should be VALUE."""
        ct_field = self._get_field(Comment, "content_type")
        # content_type is a FK to ContentType — always out of scope
        result = classify_field(ct_field, in_scope={Comment})
        assert result == FieldClass.FK_OUT_OF_SCOPE

        oid_field = self._get_field(Comment, "object_id")
        result = classify_field(oid_field, in_scope={Comment})
        assert result == FieldClass.VALUE

    def test_self_referential_reverse_fk(self):
        # Category.children is reverse FK from Category (which is in scope)
        field = self._get_field(Category, "children")
        result = classify_field(field, in_scope={Category})
        assert result == FieldClass.REVERSE_FK_IN_SCOPE


class TestGetModelFields:
    """get_model_fields should return FieldInfo for all fields on a model."""

    def test_returns_all_fields(self):
        fields = get_model_fields(Author)
        field_names = {f.name for f in fields}
        assert "id" in field_names
        assert "name" in field_names
        assert "email" in field_names
        # Reverse relations too
        assert "articles" in field_names
        assert "comments" in field_names

    def test_field_info_has_classification(self):
        fields = get_model_fields(Author, in_scope={Author, Article})
        articles_field = next(f for f in fields if f.name == "articles")
        assert articles_field.field_class == FieldClass.REVERSE_FK_IN_SCOPE

    def test_field_info_names_use_accessor_for_reverse(self):
        fields = get_model_fields(Author)
        field_names = {f.name for f in fields}
        # Should use accessor name 'reviewed_articles' not 'article'
        assert "reviewed_articles" in field_names
