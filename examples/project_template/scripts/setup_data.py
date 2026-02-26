"""Create a sample project template with sections, tasks, and tags."""

import os
import sys

import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "project_template.settings")
django.setup()

from django.contrib.auth.models import User  # noqa: E402
from projects.models import Project, Section, Tag, Task  # noqa: E402


def main():
    # Create a template owner and a target user
    template_owner, _ = User.objects.get_or_create(username="admin")
    new_user, _ = User.objects.get_or_create(username="alice")

    # Shared tags (not cloned — out of scope)
    tags = {}
    for name in ["urgent", "backend", "frontend", "design", "review"]:
        tags[name], _ = Tag.objects.get_or_create(name=name)

    # Create a project template
    project = Project.objects.create(
        name="New Starter Onboarding",
        owner=template_owner,
        is_template=True,
    )

    # Week 1
    week1 = Section.objects.create(project=project, title="Week 1 — Setup", order=0)
    t1 = Task.objects.create(
        section=week1,
        title="Get laptop and accounts",
        order=0,
        description="IT will provision your machine and create your email/Slack/GitHub accounts.",
    )
    t2 = Task.objects.create(
        section=week1,
        title="Set up local dev environment",
        order=1,
        description="Clone the repo, install dependencies, run the test suite.",
    )
    t3 = Task.objects.create(
        section=week1,
        title="Read the architecture overview",
        order=2,
        description="Familiarise yourself with the system design doc in Notion.",
    )
    t1.tags.set([tags["urgent"]])
    t2.tags.set([tags["backend"], tags["frontend"]])
    t3.tags.set([tags["review"]])

    # Week 2
    week2 = Section.objects.create(project=project, title="Week 2 — First Contributions", order=1)
    t4 = Task.objects.create(
        section=week2,
        title="Fix a good-first-issue bug",
        order=0,
        description="Pick one from the backlog and submit a PR.",
    )
    t5 = Task.objects.create(
        section=week2,
        title="Pair with a teammate on a feature",
        order=1,
        description="Shadow someone on an in-progress feature branch.",
    )
    t6 = Task.objects.create(
        section=week2,
        title="Present at team standup",
        order=2,
        description="Give a 2-minute summary of what you've learned so far.",
    )
    t4.tags.set([tags["backend"]])
    t5.tags.set([tags["backend"], tags["frontend"]])
    t6.tags.set([tags["review"]])

    print(f"Created template project: {project}")
    print(f"  Sections: {project.sections.count()}")
    print(f"  Tasks: {Task.objects.filter(section__project=project).count()}")
    print(f"  Tags (shared): {Tag.objects.count()}")
    print(f"\nUsers: {template_owner.username} (template owner), {new_user.username} (target)")


if __name__ == "__main__":
    main()
