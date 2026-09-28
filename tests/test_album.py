from fototrip.album import ExportReport


def test_report_names_the_album_and_the_counts():
    report = ExportReport(album="2026-07 Argentina", in_album=2563, exported=2551)
    rendered = report.render()
    assert '2563 photos in album "2026-07 Argentina"' in rendered
    assert "2551 exported" in rendered


def test_report_mentions_icloud_downloads_only_when_there_were_any():
    quiet = ExportReport(album="A", in_album=2, exported=2).render()
    assert "iCloud" not in quiet

    loud = ExportReport(album="A", in_album=2, exported=2, downloaded=1).render()
    assert "1 of them downloaded from iCloud" in loud


def test_report_lists_failures_with_their_reason():
    report = ExportReport(album="A", in_album=3, exported=1)
    report.failed["export failed"] = 2
    rendered = report.render()
    assert "2 skipped:" in rendered
    assert "export failed" in rendered


def test_report_omits_the_failure_block_when_nothing_failed():
    assert "skipped" not in ExportReport(album="A", in_album=1, exported=1).render()


def test_report_shows_a_human_readable_size():
    report = ExportReport(album="A", in_album=1, exported=1, bytes_written=4_900_000_000)
    assert "4.9 GB" in report.render()


def test_report_size_stays_readable_for_small_exports():
    report = ExportReport(album="A", in_album=1, exported=1, bytes_written=3_500_000)
    assert "3.5 MB" in report.render()


def test_report_omits_the_album_size_when_it_is_unknown():
    """The size is only known when the user supplies it, so 0 means unknown."""
    rendered = ExportReport(album="A", in_album=0, exported=3).render()
    assert "0 photos" not in rendered
    assert "3 exported" in rendered
