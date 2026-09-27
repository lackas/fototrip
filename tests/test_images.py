from PIL import Image

from fototrip.images import build_derivatives


def test_thumb_is_a_square_of_the_requested_size(make_jpeg, tmp_path):
    source = make_jpeg(size=(400, 600))
    build_derivatives(source, "IMG_1", tmp_path / "out", thumb_px=96)
    assert Image.open(tmp_path / "out" / "thumb" / "IMG_1.jpg").size == (96, 96)


def test_landscape_source_also_yields_a_square_thumb(make_jpeg, tmp_path):
    source = make_jpeg(size=(600, 400))
    build_derivatives(source, "IMG_1", tmp_path / "out", thumb_px=96)
    assert Image.open(tmp_path / "out" / "thumb" / "IMG_1.jpg").size == (96, 96)


def test_web_derivative_is_capped_on_the_long_edge(make_jpeg, tmp_path):
    source = make_jpeg(size=(2000, 1000))
    result = build_derivatives(source, "IMG_1", tmp_path / "out", web_px=1600)
    assert (result.web_width, result.web_height) == (1600, 800)
    assert Image.open(tmp_path / "out" / "web" / "IMG_1.jpg").size == (1600, 800)


def test_web_derivative_never_upscales(make_jpeg, tmp_path):
    """Today's sources are 480x640; they must not be blown up to 1600."""
    source = make_jpeg(size=(480, 640))
    result = build_derivatives(source, "IMG_1", tmp_path / "out", web_px=1600)
    assert (result.web_width, result.web_height) == (480, 640)


def test_orientation_is_applied_to_the_output(make_jpeg, tmp_path):
    """Orientation 6 rotates a stored 40x60 to a displayed 60x40."""
    source = make_jpeg(size=(40, 60), orientation=6)
    result = build_derivatives(source, "IMG_1", tmp_path / "out", web_px=1600)
    assert (result.web_width, result.web_height) == (60, 40)


def test_returned_paths_are_relative_and_forward_slashed(make_jpeg, tmp_path):
    result = build_derivatives(make_jpeg(), "IMG_1", tmp_path / "out")
    assert result.thumb_rel == "thumb/IMG_1.jpg"
    assert result.web_rel == "web/IMG_1.jpg"


def test_outputs_carry_no_exif(make_jpeg, tmp_path):
    """Derivatives must not leak the original GPS tags as well as the JSON."""
    build_derivatives(make_jpeg(), "IMG_1", tmp_path / "out")
    assert not Image.open(tmp_path / "out" / "web" / "IMG_1.jpg").getexif()
    assert not Image.open(tmp_path / "out" / "thumb" / "IMG_1.jpg").getexif()
