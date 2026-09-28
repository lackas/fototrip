from fototrip.album import ExportReport, _human_bytes


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


def test_report_omits_size_line_when_bytes_written_is_zero():
    """Size line is only added when bytes_written is nonzero."""
    rendered = ExportReport(album="A", in_album=1, exported=1, bytes_written=0).render()
    assert "written" not in rendered


# Human bytes boundary tests pinning unit promotion
def test_human_bytes_zero():
    """Zero bytes renders as whole number."""
    assert _human_bytes(0) == "0 B"


def test_human_bytes_bytes_stay_whole():
    """Byte values render without decimal places."""
    assert _human_bytes(847) == "847 B"
    assert _human_bytes(999) == "999 B"


def test_human_bytes_boundary_bytes_to_kb():
    """Promotion from bytes to kB happens at 1000."""
    assert _human_bytes(999) == "999 B"
    assert _human_bytes(1000) == "1.0 kB"


def test_human_bytes_kb_gets_one_decimal():
    """kilobytes render with one decimal place."""
    assert _human_bytes(3500) == "3.5 kB"


def test_human_bytes_boundary_kb_to_mb():
    """Promotion from kB to MB based on formatted value (1000 kB = 1.0 MB)."""
    assert _human_bytes(999_999) == "1.0 MB"
    assert _human_bytes(1_000_000) == "1.0 MB"


def test_human_bytes_mb_with_one_decimal():
    """Megabytes render with one decimal."""
    assert _human_bytes(3_500_000) == "3.5 MB"


def test_human_bytes_large_gb():
    """Large gigabytes render correctly (typical export size for this feature)."""
    assert _human_bytes(2_700_000_000) == "2.7 GB"


def test_human_bytes_boundary_gb_to_tb():
    """Promotion from GB to TB based on formatted value."""
    # 999_900_000_000 bytes = 999.9 GB, which formats as "999.9 GB"
    # This stays in GB; anything that would format as 1000+ GB promotes to TB
    assert _human_bytes(999_900_000_000) == "999.9 GB"
    # 1_000_000_000_000 bytes = 1000 GB = 1.0 TB
    assert _human_bytes(1_000_000_000_000) == "1.0 TB"


def test_human_bytes_above_terabyte():
    """Values above terabyte render in TB (last unit)."""
    assert _human_bytes(5_500_000_000_000) == "5.5 TB"
