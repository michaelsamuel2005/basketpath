from basketpath import extract
from basketpath.schema import EVENT_COLUMNS, ITEM_COLUMNS


def test_extraction_sql_reads_the_public_table_one_day_at_a_time():
    for sql in (extract.EVENTS_SQL, extract.ITEMS_SQL):
        assert "bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*" in sql
        assert "_TABLE_SUFFIX = @day" in sql


def test_extraction_sql_produces_every_contracted_column():
    for sql, contract in ((extract.EVENTS_SQL, EVENT_COLUMNS), (extract.ITEMS_SQL, ITEM_COLUMNS)):
        for col in contract:
            assert f"AS {col}" in sql or f" {col}," in sql or f"i.{col}" in sql or f"\n  {col}," in sql, col


def test_extract_imports_without_the_bigquery_client():
    # The BigQuery client is optional; importing the module must not need it.
    assert extract.days(extract.FIRST_DAY, extract.LAST_DAY)[-1] == extract.LAST_DAY
    assert len(extract.days(extract.FIRST_DAY, extract.LAST_DAY)) == 92
