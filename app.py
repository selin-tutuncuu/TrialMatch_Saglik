from __future__ import annotations

import hashlib
import os
from datetime import datetime
from pathlib import Path

import streamlit as st

from trialmatch.agents import DISCLAIMER, TrialMatchOrchestrator
from trialmatch.clinicaltrials import TrialApiError
from trialmatch.models import PrescreenReport
from trialmatch.presentation import (
    criterion_explanation,
    criterion_kind_label,
    decision_label,
    profile_cards,
    screening_label,
    trial_display_title,
)
from trialmatch.privacy import redact_pii
from trialmatch.profile import extract_patient_profile
from trialmatch.reporting import save_report

st.set_page_config(
    page_title="TrialMatch | Klinik Araştırmalar",
    page_icon="🎗️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
    :root {
        --tm-ink: #17233b;
        --tm-muted: #64748b;
        --tm-accent: #a63a69;
        --tm-accent-dark: #7e294f;
        --tm-soft: #fbf5f8;
        --tm-line: #e7eaf0;
        --tm-bg: #f7f8fb;
    }
    html, body, [class*="css"] { font-family: 'Segoe UI', sans-serif; }
    .stApp { background: var(--tm-bg); color: var(--tm-ink); }
    [data-testid="stHeader"] { background: rgba(247,248,251,.9); }
    [data-testid="stMainBlockContainer"] { max-width: 1180px; padding-top: 2rem; }
    h1, h2, h3 { font-family: 'Segoe UI', sans-serif; color: var(--tm-ink); }
    h1 { letter-spacing: -.04em; font-weight: 800; }
    h2 { letter-spacing: -.025em; font-weight: 700; }
    .tm-brand { color: var(--tm-accent); font-weight: 800; letter-spacing: -.04em; }
    .tm-eyebrow { color: var(--tm-accent-dark); font-size: .78rem; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; }
    .tm-subtitle { color: var(--tm-muted); font-size: 1.05rem; }
    .tm-safety {
      padding: 1rem 1.15rem; border: 1px solid #f1d8a9; border-radius: 14px;
      background: #fffaf0; color: #704b0b; margin: 1.3rem 0 1.5rem;
    }
    .tm-step {
      padding: .72rem 1rem; border: 1px solid var(--tm-line); border-radius: 999px;
      color: var(--tm-muted); background: white; font-size: .92rem; font-weight: 600;
      text-align: center;
    }
    .tm-step-active { color: var(--tm-accent-dark); border-color: #e8bfd0; background: var(--tm-soft); }
    .tm-profile-label { color: var(--tm-muted); font-size: .8rem; font-weight: 600; margin-bottom: .3rem; }
    .tm-profile-value { color: var(--tm-ink); font-size: 1rem; font-weight: 700; line-height: 1.45; overflow-wrap: anywhere; }
    .tm-status {
      display: inline-block; border-radius: 999px; padding: .32rem .72rem;
      background: #f4e8ee; color: var(--tm-accent-dark); font-size: .82rem; font-weight: 700;
    }
    .tm-source-label { color: var(--tm-muted); font-size: .82rem; font-weight: 600; }
    div.stButton > button[kind="primary"] {
      background: #e9ddf7; border-color: #d7c3ec; color: #3f2b5b;
      border-radius: 10px; padding: .62rem 1.1rem; font-weight: 700;
    }
    div.stButton > button[kind="primary"]:hover {
      background: #ddc8f0; border-color: #c9afe5; color: #35204f;
    }
    div[data-testid="stExpander"] { border-color: var(--tm-line); border-radius: 13px; background: white; }
    [data-testid="stMetric"] {
      background: white; border: 1px solid var(--tm-line); padding: .9rem 1rem;
      border-radius: 13px;
    }
    [data-testid="stMetricLabel"] { color: var(--tm-muted); }
    footer { visibility: hidden; }
    </style>
    """,
    unsafe_allow_html=True,
)

if "screened_summary" not in st.session_state:
    st.session_state.screened_summary = ""
if "report_json" not in st.session_state:
    st.session_state.report_json = ""
if "report_input_hash" not in st.session_state:
    st.session_state.report_input_hash = ""


def _load_synthetic_example() -> None:
    st.session_state.raw_summary = (
        "54 yaş kadın, meme kanseri, evre IIIA, HER2 pozitif. İstanbul."
    )
    st.session_state.report_json = ""
    st.session_state.report_input_hash = ""


header, header_note = st.columns([3, 1], vertical_alignment="center")
with header:
    st.markdown('<div class="tm-eyebrow">Klinik araştırmalara güvenli ilk bakış</div>', unsafe_allow_html=True)
    st.markdown('<h1><span class="tm-brand">TrialMatch</span></h1>', unsafe_allow_html=True)
    st.markdown(
        '<div class="tm-subtitle">Açık klinik araştırmaları inceleyin; '
        'kriterleri ve eksik bilgileri anlaşılır biçimde görün.</div>',
        unsafe_allow_html=True,
    )
with header_note:
    st.markdown(
        '<div style="text-align:right;color:#64748b;font-size:.9rem;">'
        '<strong>Meme kanseri araştırmaları</strong></div>',
        unsafe_allow_html=True,
    )

st.markdown(
    '<div class="tm-safety"><strong>Gizlilik ve kullanım sınırı</strong><br>'
    'Yalnızca kurgusal/sentetik vaka kullanın; gerçek hasta bilgisi girmeyin. '
    'Bu araç tanı koymaz, tedavi önermez ve çalışmaya kabul kararı vermez.</div>',
    unsafe_allow_html=True,
)

step_input, step_results = st.columns(2)
step_input.markdown(
    '<div class="tm-step tm-step-active">1&nbsp; Vaka özetini gözden geçir</div>',
    unsafe_allow_html=True,
)
step_results.markdown(
    '<div class="tm-step">2&nbsp; Çalışmaları ve kriterleri incele</div>',
    unsafe_allow_html=True,
)

with st.container(border=True):
    st.subheader("Vaka özeti")
    st.caption(
        "Yalnızca kurgusal/sentetik vaka kullanın. Girdi, uygulamanın çalıştığı "
        "sunucuda işlenir; arama için türetilen profil alanları ClinicalTrials.gov'a "
        "gönderilebilir. Gerçek hasta veya tanımlayıcı bilgi girmeyin."
    )
    raw_summary = st.text_area(
        "Kurgusal vaka metni",
        key="raw_summary",
        height=125,
        placeholder="Örnek: 54 yaş kadın, meme kanseri, evre IIIA, HER2 pozitif. İstanbul.",
        label_visibility="collapsed",
    )
    example_col, scan_col = st.columns([1, 2], vertical_alignment="center")
    example_col.button(
        "Kurgusal örneği doldur",
        on_click=_load_synthetic_example,
    )
    if scan_col.button("Gizlilik taraması yap ve profili göster", type="primary"):
        if not raw_summary.strip():
            st.error("Devam etmek için kurgusal vaka metni girin.")
        else:
            redaction = redact_pii(raw_summary)
            st.session_state.screened_summary = redaction.text
            st.session_state.pii_types = redaction.pii_types
            st.session_state.report_json = ""
            st.session_state.report_input_hash = ""
            st.rerun()

if st.session_state.screened_summary:
    if st.session_state.get("pii_types"):
        st.info(
            "Gizlilik taraması bazı kişisel bilgi benzeri alanları maskeledi: "
            + ", ".join(st.session_state.pii_types)
        )
    with st.container(border=True):
        st.subheader("Profil önizlemesi")
        sanitized = st.text_area(
            "Taranmış metin (gerekirse düzenleyin)",
            key="screened_summary",
            height=110,
        )
        preview = extract_patient_profile(sanitized)
        cards = profile_cards(preview)
        for start in range(0, len(cards), 4):
            columns = st.columns(4)
            for column, (label, value) in zip(columns, cards[start:start + 4]):
                with column:
                    st.markdown(
                        f'<div class="tm-profile-label">{label}</div>'
                        f'<div class="tm-profile-value">{value}</div>',
                        unsafe_allow_html=True,
                    )
        if preview.biomarkers or preview.prior_treatments or preview.treatment_history_negatives:
            st.caption(
                "Özet içindeki ilgili bilgiler: "
                + ", ".join(
                    item
                    for item in (
                        *[f"{marker.name}: {marker.value or 'sonuç belirtilmedi'}" for marker in preview.biomarkers],
                        *[f"Önceki tedavi: {item}" for item in preview.prior_treatments],
                        *[f"Alınmadığı belirtilen tedavi: {item}" for item in preview.treatment_history_negatives],
                    )
                )
            )
        st.caption(
            "Lütfen profil alanlarını kontrol edin. Otomatik çıkarım eksik veya hatalı olabilir."
        )
        run_col, help_col = st.columns([2, 3], vertical_alignment="center")
        run_clicked = run_col.button(
            "Açık çalışmaları ara ve ön değerlendirmeyi başlat",
            type="primary",
            use_container_width=True,
        )
        help_col.caption(
            "ClinicalTrials.gov'dan güncel kayıtlar alınır. İnternet bağlantısı gerekir."
        )

    if run_clicked:
        if "[REDACTED]" in sanitized:
            st.info(
                "Maskelenen alanlar aramaya gönderilmez. Profilde yalnızca "
                "maskesiz ve açıkça görünen bilgiler kullanılır."
            )
        try:
            with st.spinner("Açık çalışmalar aranıyor; bu işlem biraz sürebilir."):
                report = TrialMatchOrchestrator(
                    cache_dir=Path(os.getenv("TRIALMATCH_CACHE_DIR", "data/cache")),
                    log_path=Path(os.getenv("TRIALMATCH_LOG_PATH", "data/cache/audit.jsonl")),
                    trace_path=Path(os.getenv("TRIALMATCH_TRACE_PATH", "data/cache/traces.jsonl")),
                    enable_embeddings=os.getenv(
                        "TRIALMATCH_ENABLE_EMBEDDINGS", "false"
                    ).casefold() == "true",
                ).run(sanitized)
            st.session_state.report_json = report.model_dump_json()
            st.session_state.report_input_hash = hashlib.sha256(
                sanitized.encode("utf-8")
            ).hexdigest()
        except (TrialApiError, RuntimeError, OSError, ValueError) as error:
            st.session_state.report_json = ""
            if "HTTP 429" in str(error):
                st.error(
                    "ClinicalTrials.gov kısa sürede çok sayıda isteği sınırladı. "
                    "Biraz bekleyip yeniden deneyin."
                )
            elif "timed out" in str(error).casefold():
                st.error(
                    "ClinicalTrials.gov yanıt vermedi. İnternet bağlantınızı "
                    "kontrol edip biraz sonra yeniden deneyin."
                )
            else:
                st.error(
                    "Çalışma araması tamamlanamadı. Bağlantıyı kontrol edip "
                    "biraz sonra yeniden deneyin."
                )

    current_hash = hashlib.sha256(
        st.session_state.screened_summary.encode("utf-8")
    ).hexdigest()
    if st.session_state.report_json and current_hash != st.session_state.report_input_hash:
        st.info("Vaka özeti son aramadan sonra değişti. Güncel sonuçlar için yeniden arama yapın.")
    elif st.session_state.report_json:
        report = PrescreenReport.model_validate_json(st.session_state.report_json)
        st.markdown("---")
        st.markdown('<div class="tm-eyebrow">Sonuç</div>', unsafe_allow_html=True)
        st.header("Ön değerlendirme")

        if report.rejected:
            st.error(report.refusal_reason or "Bu istek bu aracın kapsamı dışındadır.")
        else:
            if report.patient_explanation:
                st.markdown(
                    f'<div class="tm-safety" style="border-color:#dbe5f1;background:#f3f7fc;color:#243b5a;">'
                    f'<strong>Sade dilde özet</strong><br>{report.patient_explanation}</div>',
                    unsafe_allow_html=True,
                )
            with st.expander("Okunabilirlik ölçümü hakkında"):
                st.caption(
                    f"Türkçe Ateşman okunabilirlik tahmini: "
                    f"{report.readability_score or 0:.1f}/100. Bu yaklaşık bir dil ölçümüdür; "
                    "tıbbi doğruluk veya anlama testi değildir."
                )
            possible = sum(
                item.screening_status == "possible_match_for_clinician_review"
                for item in report.trials
            )
            needs_info = sum(
                item.screening_status == "needs_more_information"
                for item in report.trials
            )
            other = sum(
                item.screening_status == "does_not_appear_to_meet"
                for item in report.trials
            )
            metric_cols = st.columns(4)
            metric_cols[0].metric("İncelenen çalışma", len(report.trials))
            metric_cols[1].metric("Uzman incelemesine öncelik", possible)
            metric_cols[2].metric("Ek bilgi gerekli", needs_info)
            metric_cols[3].metric("Karşılanmayan maddeler olabilir", other)

            for warning in report.warnings:
                if warning not in {report.disclaimer, DISCLAIMER}:
                    st.warning(warning)

            if not report.trials:
                st.info(
                    "Bu arama ölçütleriyle gösterilecek çalışma bulunamadı. "
                    "Bu, hiçbir uygun araştırma olmadığı anlamına gelmez."
                )

            for evaluation in report.trials:
                trial = evaluation.trial
                unknown_items = [
                    item
                    for item in evaluation.criteria
                    if item.decision == "UNKNOWN"
                ]
                with st.expander(
                    f"{trial_display_title(trial.title)}  ·  {trial.nct_id}",
                    expanded=len(report.trials) == 1,
                ):
                    with st.expander("Özgün çalışma başlığı"):
                        st.write(trial.title)
                    status_text = screening_label(evaluation)
                    st.markdown(
                        f'<span class="tm-status">{status_text}</span>',
                        unsafe_allow_html=True,
                    )
                    if evaluation.criteria:
                        if unknown_items:
                            st.caption(
                                f"{len(evaluation.criteria)} kriter incelendi · "
                                f"{len(unknown_items)} madde için ek bilgi gerekiyor."
                            )
                        else:
                            st.caption(
                                f"{len(evaluation.criteria)} kriter incelendi."
                            )
                    st.markdown(
                        f'<div style="margin-top:.75rem">'
                        f'<span class="tm-source-label">Kaynak:</span> '
                        f'<a href="{trial.source_url}" target="_blank" rel="noopener noreferrer">'
                        f'ClinicalTrials.gov kaydını aç</a> &nbsp;·&nbsp; '
                        f'<span class="tm-source-label">Durum:</span> '
                        f'{ "Katılımcı alıyor" if trial.status == "RECRUITING" else "Kaynak durumunu inceleyin" }'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                    fetched = datetime.fromisoformat(trial.fetched_at)
                    st.caption(
                        "Son kontrol: "
                        + fetched.strftime("%d.%m.%Y %H:%M UTC")
                    )
                    if trial.nearest_location:
                        st.markdown(
                            f"**En yakın kayıtlı araştırma merkezi:** "
                            f"{trial.nearest_location} · yaklaşık {trial.distance_km} km"
                        )

                    with st.expander(
                        f"Kriter ayrıntıları ({len(evaluation.criteria)})"
                    ):
                        if unknown_items:
                            st.caption(
                                "Bilgi eksik görünen maddeler için gerekli "
                                "klinik bilgiyi uzmanla doğrulayın."
                            )
                        for index, item in enumerate(evaluation.criteria, start=1):
                            with st.container(border=True):
                                criterion_col, decision_col = st.columns(
                                    [4, 2], vertical_alignment="center"
                                )
                                criterion_col.markdown(
                                    f"**Madde {index} · {criterion_kind_label(item)}**"
                                )
                                decision_col.markdown(
                                    f'<span class="tm-status">{decision_label(item)}</span>',
                                    unsafe_allow_html=True,
                                )
                                if item.decision != "UNKNOWN":
                                    st.write(criterion_explanation(item))
                                if item.patient_evidence:
                                    st.caption(
                                        f"Vaka özetindeki dayanak: “{item.patient_evidence}”"
                                    )
                                with st.expander(
                                    "ClinicalTrials.gov kaynağındaki özgün kriter"
                                ):
                                    st.write(item.criterion_quote)

            st.info(DISCLAIMER)
            with st.container(border=True):
                st.markdown("**Raporu uygulama sunucusuna kaydet**")
                st.caption(
                    "Rapor uygulamanın çalıştığı sunucudaki reports klasörüne "
                    "kaydedilir; bulut demosunda bu, hosting ortamıdır ve rapor "
                    "bilgisayarınıza indirilmez. Yalnızca sentetik vaka kullanın."
                )
                approved = st.checkbox(
                    "Bu raporun uygulama sunucusuna kaydedilmesini onaylıyorum.",
                    key="approve_report_save",
                )
                if st.button("Raporu kaydet", disabled=not approved):
                    try:
                        saved_path = save_report(
                            report,
                            approved=approved,
                            output_dir=Path(
                                os.getenv("TRIALMATCH_REPORT_DIR", "reports")
                            ),
                        )
                        st.success(f"Rapor kaydedildi: {saved_path}")
                    except (OSError, PermissionError, ValueError) as error:
                        st.error(f"Rapor kaydedilemedi: {error}")

st.markdown(
    '<div style="text-align:center;color:#718096;font-size:.82rem;padding:2rem 0 1rem;">'
    'TrialMatch · ClinicalTrials.gov verilerine dayalı eğitim amaçlı ön değerlendirme'
    '</div>',
    unsafe_allow_html=True,
)
