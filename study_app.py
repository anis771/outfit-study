"""Participant-facing study site (pre-generated results). Mobile-friendly, one column. No participant code:
a visitor presses Start and gets a personal link (?p=<id>) to come back to.

Stage 1  Start -> consent -> pre-questionnaire -> preference + style request + full-body photo (+ optional email)
Stage 2  (after the researcher publishes results) -> own outfits (try-on + products) -> ratings -> post-questionnaire

Storage (one file per participant, so simultaneous participants never overwrite each other):
  participants/<id>.json       created at Start
  submissions/<id>/photo.png   EXIF-stripped photo            submissions/<id>/pre.json  answers + request
  submissions/<id>/contact.json  optional email (kept apart from answers)
  results/<id>/manifest.json   published by admin.py only after the researcher approved the images
  responses/<id>/post.json     ratings + post answers
Backend: local folder STUDY_DIR (default D:/fashion_project_data/user_study), or a PRIVATE Hugging Face dataset when
STUDY_HF_DATASET (repo id) and HF_TOKEN are set (Hugging Face Space deployment).
Run locally:  streamlit run user_study/study_app.py --server.port 8502
"""

from __future__ import annotations

import io
import json
import os
import secrets
import time
from pathlib import Path

import streamlit as st
from PIL import Image, ImageOps

Q = json.loads((Path(__file__).with_name("questionnaire.json")).read_text(encoding="utf-8"))
MAX_SIDE = 2048
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


from storage import get_store, write_json as _write_json


@st.cache_resource
def store():
    return get_store()


def write_json(rel, obj):
    _write_json(store(), rel, obj)

st.set_page_config(page_title=Q["study_title"], page_icon="👗", layout="centered", initial_sidebar_state="collapsed")
st.markdown("""<style>
#MainMenu, header, footer {visibility: hidden;}
.block-container {padding-top: 1.2rem; max-width: 720px;}
div[data-testid="stImage"] img {border-radius: 6px;}
</style>""", unsafe_allow_html=True)


def question(item, key_prefix=""):
    key = key_prefix + item["id"]
    if item["type"] == "likert":
        v = st.radio(item["text"], list(range(1, 8)), index=None, horizontal=True, key=key)
        st.caption(f"1 = {item['low']} · 7 = {item['high']}")
        return v
    if item["type"] == "choice":
        return st.radio(item["text"], item["options"], index=None, key=key)
    return st.text_area(item["text"], key=key)


def answered(items, answers):
    return all(item.get("optional") or answers.get(item["id"]) not in (None, "") for item in items)


def personal_link(code: str) -> str:
    base = ""
    try:
        base = (st.context.url or "").split("?")[0]
    except Exception:
        pass
    return f"{base}?p={code}" if base else f"?p={code}"


def stage1(code):
    st.subheader("Step 1 of 2: Consent and questionnaire")
    st.markdown(Q["consent"]["text"])
    if not st.checkbox(Q["consent"]["checkbox"], key="consent"):
        return
    st.divider()
    answers = {it["id"]: question(it, "pre_") for it in Q["pre"]}
    st.divider()
    st.markdown("**Your outfit request**")
    pref = st.radio("Show me outfits from the catalog section", ["Female", "Male", "Unisex"], index=None,
                    horizontal=True, key="pref")
    req = st.text_input("Describe the outfit you are looking for (e.g. 'elegant formal outfit')", key="req")
    st.markdown("**Your photo**: one person, full body from head to feet, standing, good light, plain background "
                "if possible.")
    up = st.file_uploader("Upload a photo", type=["jpg", "jpeg", "png", "webp"], key="photo")
    img = None
    if up is not None:
        try:
            img = ImageOps.exif_transpose(Image.open(up)).convert("RGB")
            img.thumbnail((MAX_SIDE, MAX_SIDE))
            st.image(img, caption="Your photo (only the research team can see it)", width=260)
        except Exception:
            st.error("This file could not be read as an image. Please try another photo.")
            img = None
    email = st.text_input("Email for a notification when your outfits are ready (optional)", key="email")
    ready = answered(Q["pre"], answers) and pref and req.strip() and img is not None
    if st.button("Submit", type="primary", disabled=not ready, use_container_width=True):
        with st.spinner("Saving…"):
            buf = io.BytesIO()
            img.save(buf, format="PNG")                         # re-encoded: EXIF / GPS metadata removed
            store().write(f"submissions/{code}/photo.png", buf.getvalue())
            if email.strip():                                   # contact data kept apart from the answers
                write_json(f"submissions/{code}/contact.json", {"email": email.strip()})
            write_json(f"submissions/{code}/pre.json", {"code": code, "consent": True,
                                                         "submitted": time.strftime("%Y-%m-%d %H:%M:%S"),
                                                         "answers": answers, "preference": pref,
                                                         "request": req.strip()})
        st.rerun()
    if not ready:
        st.caption("Please answer all questions, choose a catalog section, describe the outfit and upload a photo.")


def stage2(code, manifest):
    st.subheader("Step 2 of 2: Your outfits")
    st.write(f"Your request: *{manifest.get('request', '')}*. Please look at each outfit and rate it.")
    ratings = {}
    for k, o in enumerate(manifest["outfits"], 1):
        st.markdown(f"### Outfit {k}")
        st.image(store().path(f"results/{code}/{o['tryon_image']}"), use_container_width=True)
        if o.get("products"):
            cols = st.columns(min(4, len(o["products"])))
            for i, pr in enumerate(o["products"]):
                with cols[i % len(cols)]:
                    st.image(store().path(f"results/{code}/{pr['image']}"), caption=pr.get("label", ""),
                             use_container_width=True)
        if o.get("note"):
            st.caption(o["note"])
        ratings[o["id"]] = {it["id"]: question(it, f"o{k}_") for it in Q["per_outfit"]}
        st.divider()
    st.markdown("### Final questions")
    post = {it["id"]: question(it, "post_") for it in Q["post"]}
    ready = all(answered(Q["per_outfit"], r) for r in ratings.values()) and answered(Q["post"], post)
    if st.button("Submit answers", type="primary", disabled=not ready, use_container_width=True):
        with st.spinner("Saving…"):
            write_json(f"responses/{code}/post.json", {"code": code, "submitted": time.strftime("%Y-%m-%d %H:%M:%S"),
                                                         "outfit_ratings": ratings, "answers": post,
                                                         "manifest_version": manifest.get("version")})
        st.rerun()
    if not ready:
        st.caption("Please answer every question (the comment box is optional).")


def main():
    st.title(Q["study_title"])
    code = (st.query_params.get("p") or "").strip().upper()
    if not code:
        st.write("Thank you for your interest. The study takes about 10 minutes now and about 10 minutes later, "
                 "when your outfits are ready.")
        if st.button("Start", type="primary", use_container_width=True):
            new = "".join(secrets.choice(ALPHABET) for _ in range(10))
            write_json(f"participants/{new}.json", {"created": time.strftime("%Y-%m-%d %H:%M:%S")})
            st.query_params["p"] = new
            st.rerun()
        return
    if not (len(code) == 10 and set(code) <= set(ALPHABET)) or not store().exists(f"participants/{code}.json"):
        st.error("This personal link is not valid. Please open the study link again and press Start.")
        return
    with st.expander("Your personal link (bookmark it to come back later)"):
        st.code(personal_link(code), language=None)
    if store().exists(f"responses/{code}/post.json"):
        st.success("Thank you! You have completed the study.")
        return
    manifest = store().read_json(f"results/{code}/manifest.json")
    if manifest:
        stage2(code, manifest)
    elif store().exists(f"submissions/{code}/pre.json"):
        st.success("Thank you! Your answers and photo were received. Your outfits will be ready within a few days.")
        st.markdown("**Save this personal link** to see your outfits later:")
        st.code(personal_link(code), language=None)
    else:
        stage1(code)


main()
