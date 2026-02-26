from django.conf import settings
from django.db import models


class Project(models.Model):
    name = models.CharField(max_length=200)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="projects"
    )
    is_template = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "projects"

    def __str__(self):
        return self.name


class Section(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="sections")
    title = models.CharField(max_length=200)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        app_label = "projects"
        ordering = ["order"]

    def __str__(self):
        return self.title


class Tag(models.Model):
    name = models.CharField(max_length=50, unique=True)

    class Meta:
        app_label = "projects"

    def __str__(self):
        return self.name


class Task(models.Model):
    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name="tasks")
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    tags = models.ManyToManyField(Tag, blank=True, related_name="tasks")
    order = models.PositiveIntegerField(default=0)

    class Meta:
        app_label = "projects"
        ordering = ["order"]

    def __str__(self):
        return self.title
