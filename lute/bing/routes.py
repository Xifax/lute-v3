"""
Getting and saving image search results.

Image search is done via DuckDuckGo (the `ddgs` package) rather than
scraping Bing's html, which was fragile and returned mostly irrelevant
images once Bing changed its markup.
"""

import os
import datetime
import hashlib
import urllib.request
from flask import (
    Blueprint,
    request,
    Response,
    render_template,
    jsonify,
    current_app,
    url_for,
)

from ddgs import DDGS


bp = Blueprint("bing", __name__, url_prefix="/bing")


@bp.route(
    "/search_page/<int:langid>/<string:text>/<string:searchstring>", methods=["GET"]
)
def bing_search_page(langid, text, searchstring):
    """
    Load initial empty search page, passing real URL for subsequent ajax call to get images.

    Sometimes Bing image searches block or fail, so providing the initial empty search page
    lets the user know work is in progress.  The user can therefore interact with the page
    immediately. The template for this route then makes an ajax call to the "bing_search()"
    method below which actually does the search.
    """

    # Create URL for bing_search and pass into template.
    search_url = url_for(
        "bing.bing_search", langid=langid, text=text, searchstring=searchstring
    )

    return render_template(
        "imagesearch/index.html", langid=langid, text=text, search_url=search_url
    )


@bp.route("/search/<int:langid>/<string:text>/<string:searchstring>", methods=["GET"])
def bing_search(langid, text, searchstring):  # pylint: disable=unused-argument
    """
    Do an image search via DuckDuckGo.

    "searchstring" is accepted (and still passed in by bing_search_page /
    the front-end url_for call) for backwards compatibility with the old
    Bing-query-string mechanism, but it's no longer used: ddgs takes a
    plain query and its own set of typed parameters instead of a raw
    query-string blob.
    """

    # Searching for images slows acceptance tests.  If NO_BING_IMAGES
    # environment setting, don't do a search.
    if "NO_BING_IMAGES" in os.environ:
        return render_template(
            "imagesearch/index.html", langid=langid, text=text, images=[]
        )

    error_msg = ""
    images = []

    try:
        ddgs = DDGS()
        results = ddgs.images(
            query=text,
            safesearch="moderate",
            max_results=25,
        )
        images = [s for s in (_build_image_struct(r) for r in results) if s]
    except Exception as e:  # pylint: disable=broad-exception-caught
        error_msg = str(e)

    ret = {
        "langid": langid,
        "text": text,
        "images": images,
        "error_message": error_msg,
    }
    return jsonify(ret)


def _build_image_struct(result):
    """
    Convert one ddgs image-search result into the {"html", "src"} shape
    that the imagesearch template/JS expects (it previously came from a
    scraped Bing <img> tag).

    "src" is the full-resolution image, used by bing_save() when the user
    clicks an image to save it. "html" is a small <img> snippet built from
    the thumbnail, so the search results grid stays cheap to render.
    """
    src = result.get("image")
    if not src:
        return None
    thumb = result.get("thumbnail") or src
    title = (result.get("title") or "").replace('"', "'")
    html = f'<img class="rms_img" src="{thumb}" title="{title}">'
    return {"html": html, "src": src, "thumb": thumb}


def _get_dir_and_filename(langid, text):
    "Make a directory if needed, return [dir, filename]"
    datapath = current_app.config["DATAPATH"]
    image_dir = os.path.join(datapath, "userimages", langid)
    if not os.path.exists(image_dir):
        os.makedirs(image_dir)

    now = datetime.datetime.now()
    timestamp = now.strftime("%Y%m%d_%H%M%S%f")[:-3]
    hash_part = hashlib.md5(text.encode()).hexdigest()[:8]
    filename = f"{timestamp}_{hash_part}.jpeg"
    return [image_dir, filename]


@bp.route("/save", methods=["POST"])
def bing_save():
    """
    Save the posted image data to DATAPATH/userimages,
    returning the filename.
    """
    src = request.form["src"]
    text = request.form["text"]
    langid = request.form["langid"]

    imgdir, filename = _get_dir_and_filename(langid, text)
    destfile = os.path.join(imgdir, filename)
    with urllib.request.urlopen(src) as response, open(destfile, "wb") as out_file:
        out_file.write(response.read())

    ret = {
        "url": f"/userimages/{langid}/{filename}",
        "filename": filename,
    }
    return jsonify(ret)


@bp.route("/manual_image_post", methods=["POST"])
def manual_image_post():
    """
    For manual posts of images (not bing image clicks).
    Save the posted image data to DATAPATH/userimages,
    returning the filename.
    """
    text = request.form["text"]
    langid = request.form["langid"]

    if "manual_image_file" not in request.files:
        return Response("No file part in request", status=400)

    f = request.files["manual_image_file"]
    if f.filename == "":
        return Response("No selected file", status=400)

    imgdir, filename = _get_dir_and_filename(langid, text)
    destfile = os.path.join(imgdir, filename)
    f.save(destfile)

    ret = {
        "url": f"/userimages/{langid}/{filename}",
        "filename": filename,
    }
    return jsonify(ret)
