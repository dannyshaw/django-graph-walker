"""Clone a project template for a new user.

This is the core use case: take a template project with all its sections and
tasks, duplicate it into a new user's account, and reassign ownership — without
manually writing per-model clone logic.
"""

import os
import sys

import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "project_template.settings")
django.setup()

from django.contrib.auth.models import User  # noqa: E402
from projects.models import Project, Section, Task  # noqa: E402

from django_graph_walker import GraphSpec, GraphWalker  # noqa: E402
from django_graph_walker.actions.clone import Clone  # noqa: E402
from django_graph_walker.spec import KeepOriginal, Override  # noqa: E402


def clone_project_for_user(project: Project, user: User):
    """Duplicate a project template and assign it to a new user."""

    spec = GraphSpec(
        {
            Project: {
                # Reassign to the new user and mark as non-template
                "owner": Override(lambda inst, ctx: ctx["user"]),
                "is_template": Override(False),
                "name": Override(lambda inst, ctx: f"{inst.name} — {ctx['user'].username}"),
            },
            Section: {},
            Task: {
                # Tags are shared across projects — keep original references, don't clone
                "tags": KeepOriginal(),
            },
            # Tag is deliberately NOT in scope. Out-of-scope M2M targets are
            # preserved automatically — tasks will point to the same shared tags.
        }
    )

    result = GraphWalker(spec).walk(project)
    cloned = Clone(spec).execute(result, ctx={"user": user})

    return cloned.get_clone(project)


def main():
    template = Project.objects.filter(is_template=True).first()
    if template is None:
        print("No template project found. Run setup_data.py first.")
        sys.exit(1)

    user = User.objects.get(username="alice")

    print(f"Cloning '{template.name}' for user '{user.username}'...\n")

    new_project = clone_project_for_user(template, user)

    # Show what was created
    print(f"New project: {new_project.name}")
    print(f"  Owner:    {new_project.owner.username}")
    print(f"  Template: {new_project.is_template}")
    print(f"  Sections: {new_project.sections.count()}")

    for section in new_project.sections.all():
        print(f"\n  {section.title}:")
        for task in section.tasks.all():
            tag_names = ", ".join(task.tags.values_list("name", flat=True))
            print(f"    - {task.title}" + (f"  [{tag_names}]" if tag_names else ""))


if __name__ == "__main__":
    main()
