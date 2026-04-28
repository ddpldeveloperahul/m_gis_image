from django.db import migrations


def add_status_column_if_missing(apps, schema_editor):
    table_name = "myapp_changeresult"
    column_name = "status"

    with schema_editor.connection.cursor() as cursor:
        existing_columns = [
            column_info[1]
            for column_info in cursor.execute(f"PRAGMA table_info({table_name})").fetchall()
        ]

        if column_name not in existing_columns:
            cursor.execute(
                f"ALTER TABLE {table_name} "
                f"ADD COLUMN {column_name} varchar(20) NOT NULL DEFAULT 'pending'"
            )


class Migration(migrations.Migration):

    dependencies = [
        ("myapp", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(add_status_column_if_missing, migrations.RunPython.noop),
    ]
