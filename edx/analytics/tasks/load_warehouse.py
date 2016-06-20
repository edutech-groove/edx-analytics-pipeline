"""
Workflow to load the warehouse, this serves as a replacement for pentaho loading.
"""
import logging
import luigi

from edx.analytics.tasks.load_internal_reporting_certificates import LoadInternalReportingCertificatesToWarehouse
from edx.analytics.tasks.load_internal_reporting_country import LoadInternalReportingCountryToWarehouse
from edx.analytics.tasks.load_internal_reporting_course import LoadInternalReportingCourseToWarehouse
from edx.analytics.tasks.load_internal_reporting_user_activity import LoadInternalReportingUserActivityToWarehouse
from edx.analytics.tasks.load_internal_reporting_user_course import LoadInternalReportingUserCourseToWarehouse
from edx.analytics.tasks.load_internal_reporting_user import LoadInternalReportingUserToWarehouse
from edx.analytics.tasks.course_catalog import DailyLoadSubjectsToVerticaTask
from edx.analytics.tasks.vertica_load import VerticaCopyTaskMixin, CredentialFileVerticaTarget

from edx.analytics.tasks.util.hive import WarehouseMixin
from edx.analytics.tasks.url import ExternalURL

log = logging.getLogger(__name__)


class SchemaManagementTask(VerticaCopyTaskMixin, luigi.Task):

    def requires(self):
        return {
            'credentials': ExternalURL(self.credentials)
        }

    def output(self):
        return CredentialFileVerticaTarget(
            credentials_target=self.input()['credentials'],
            table='',
            schema=self.schema,
            update_id=self.update_id()
        )

    def update_id(self):
        return str(self)

    def complete(self):
        return True

class PreLoadWarehouseTask(SchemaManagementTask):

    priority = 100

    def run(self):
        connection = self.output().connect()

        warehouse_schema_last = self.schema + '_last'
        warehouse_schema_loading = self.schema + '_loading'

        try:
            connection.cursor().execute("DROP SCHEMA IF EXISTS {schema} CASCADE;".format(schema=warehouse_schema_last))
            connection.cursor().execute("DROP SCHEMA IF EXISTS {schema} CASCADE;".format(schema=warehouse_schema_loading))
            connection.cursor().execute("CREATE SCHEMA IF NOT EXISTS {schema}".format(schema=warehouse_schema_loading))
        except Exception as exc:
            log.exception("Rolled back the transaction; exception raised: %s", str(exc))
            connection.rollback()
            raise
        finally:
            connection.close()


class PostLoadWarehouseTask(SchemaManagementTask):

    priority = -100

    def run(self):
        connection = self.output().connect()

        warehouse_schema_last = self.schema + '_last'
        warehouse_schema_loading = self.schema + '_loading'

        try:
            # TODO: validation.
            self.output().touch(connection)
            connection.cursor().execute("ALTER SCHEMA {schema} RENAME TO {schema_last};".format(schema=self.schema, schema_last=warehouse_schema_last))
            connection.cursor().execute("ALTER SCHEMA {schema_loading} RENAME TO {schema};".format(schema_loading=warehouse_schema_loading, schema=self.schema))
            connection.cursor().execute("GRANT USAGE ON SCHEMA {schema} TO analyst;".format(schema=self.schema))
            connection.cursor().execute("GRANT SELECT ON ALL TABLES IN SCHEMA {schema} TO analyst;".format(schema=self.schema))
        except Exception as exc:
            log.exception("Rolled back the transaction; exception raised: %s", str(exc))
            connection.rollback()
            raise
        finally:
            connection.close()


class LoadWarehouse(WarehouseMixin, luigi.WrapperTask):
    """Runs the workflow needed to load warehouse."""

    date = luigi.DateParameter()

    n_reduce_tasks = luigi.Parameter()

    # We are not using VerticaCopyTaskMixin as OverwriteOutputMixin changes the complete() method behavior.
    schema = luigi.Parameter(
        config_path={'section': 'vertica-export', 'name': 'schema'},
        description='The schema to which to write.',
    )
    credentials = luigi.Parameter(
        config_path={'section': 'vertica-export', 'name': 'credentials'},
        description='Path to the external access credentials file.',
    )

    overwrite = luigi.BooleanParameter(default=False)

    def requires(self):
        kwargs = {
            'schema': self.schema,
            'credentials': self.credentials,
            'overwrite': self.overwrite,
            'warehouse_path': self.warehouse_path,
        }

        yield PreLoadWarehouseTask(schema=self.schema, credentials=self.credentials)
        yield (
            LoadInternalReportingCertificatesToWarehouse(
                date=self.date,
                **kwargs
            ),
            # LoadInternalReportingCountryToWarehouse(
            #     date=self.date,
            #     n_reduce_tasks=self.n_reduce_tasks,
            #     **kwargs
            # ),
            # LoadInternalReportingCourseToWarehouse(
            #     date=self.date,
            #     n_reduce_tasks=self.n_reduce_tasks,
            #     **kwargs
            # ),
            # LoadInternalReportingUserCourseToWarehouse(
            #     date=self.date,
            #     n_reduce_tasks=self.n_reduce_tasks,
            #     **kwargs
            # ),
            # LoadInternalReportingUserActivityToWarehouse(
            #     date=self.date,
            #     n_reduce_tasks=self.n_reduce_tasks,
            #     **kwargs
            # ),
            # LoadInternalReportingUserToWarehouse(
            #     date=self.date,
            #     n_reduce_tasks=self.n_reduce_tasks,
            #     **kwargs
            # ),
            # DailyLoadSubjectsToVerticaTask(
            #     date=self.date,
            #     **kwargs
            # )
        )
        yield PostLoadWarehouseTask(schema=self.schema, credentials=self.credentials)

    def output(self):
        return [task.output() for task in self.requires()]
