from app.database import Database
from pathlib import Path


class ProjectManager:

    def __init__(self):
        self.db = Database()


    def create_project(
        self,
        name,
        path,
        description=""
    ):

        project_path = Path(path)

        project_path.mkdir(
            parents=True,
            exist_ok=True
        )

        self.db.execute(
            """
            INSERT INTO projects
            (
                name,
                path,
                description
            )
            VALUES (?, ?, ?)
            """,
            (
                name,
                str(project_path),
                description
            )
        )

        return {
            "name": name,
            "path": str(project_path)
        }


    def list_projects(self):

        cursor = self.db.execute(
            """
            SELECT *
            FROM projects
            ORDER BY id
            """
        )

        return [
            dict(row)
            for row in cursor.fetchall()
        ]
