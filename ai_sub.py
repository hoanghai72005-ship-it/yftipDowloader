import os
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

import re
import sys
import json
import math
import glob
import html
import wave
import shutil
import ctypes
import unicodedata
import tempfile
import subprocess
import difflib
import requests

from sub_rules import (
    SUBTITLE_HALLUCINATION_PATTERNS,
    HALLUCINATION_TAIL_STRIPS,
    DANGLING_END_WORDS_ALL,
    SENTENCE_STARTER_WORDS_ALL,
    SPLIT_COMPOUND_PAIRS_VI,
    NONSENSE_BIGRAMS_VI,
    CONTEXTUAL_COLLOCATION_FIXES_VI,
)


def _setup_cuda_dll_paths(extra_dir: str = None):
    if os.name != 'nt':
        return

    candidate_dirs = []
    if extra_dir and os.path.isdir(extra_dir):
        candidate_dirs.append(extra_dir)

    for p in sys.path:
        if not p or not os.path.isdir(p):
            continue
        candidate_dirs.extend([
            os.path.join(p, "nvidia", "cublas", "bin"),
            os.path.join(p, "nvidia", "cudnn", "bin"),
            os.path.join(p, "nvidia", "cuda_runtime", "bin"),
            os.path.join(p, "torch", "lib"),
        ])

    current_path = os.environ.get("PATH", "")
    for d in candidate_dirs:
        if os.path.isdir(d):
            if d not in current_path:
                os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
            try:
                os.add_dll_directory(d)
            except Exception:
                pass


def _is_cuda_available_and_loadable(extra_dir: str = None) -> bool:
    _setup_cuda_dll_paths(extra_dir)
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() <= 0:
            return False
        if os.name == 'nt':
            ctypes.WinDLL("cublas64_12.dll")
        return True
    except Exception:
        return False


def _get_ffmpeg_exe(ffmpeg_dir: str = None) -> str:
    if ffmpeg_dir:
        custom_ffmpeg = os.path.join(ffmpeg_dir, 'ffmpeg.exe' if os.name == 'nt' else 'ffmpeg')
        if os.path.exists(custom_ffmpeg):
            return custom_ffmpeg
    return "ffmpeg"


def _try_demucs_separation(input_path: str, out_vocal_wav: str, out_beat_wav: str,
                           ffmpeg_dir: str = None, progress_callback=None) -> bool:
    try:
        import demucs.separate
    except ImportError:
        return False

    temp_out_dir = tempfile.mkdtemp(prefix="demucs_stems_")
    creationflags = 0x08000000 if os.name == 'nt' else 0
    try:
        if progress_callback:
            progress_callback(28, "AI Demucs: Đang tách hoàn toàn Giọng hát và nhạc Beat bằng mạng Nơ-ron...")

        env = os.environ.copy()
        if ffmpeg_dir:
            env["PATH"] = ffmpeg_dir + os.pathsep + env.get("PATH", "")

        cmd = [
            sys.executable, "-m", "demucs.separate",
            "-n", "htdemucs",
            "--two-stems", "vocals",
            "-o", temp_out_dir,
            input_path
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             env=env, creationflags=creationflags, timeout=600)
        if res.returncode != 0:
            return False

        found_vocals = glob.glob(os.path.join(temp_out_dir, "**", "vocals.wav"), recursive=True)
        found_no_vocals = glob.glob(os.path.join(temp_out_dir, "**", "no_vocals.wav"), recursive=True)

        if found_vocals and out_vocal_wav:
            shutil.copy2(found_vocals[0], out_vocal_wav)
        if found_no_vocals and out_beat_wav:
            shutil.copy2(found_no_vocals[0], out_beat_wav)

        ok_vocal = (not out_vocal_wav) or (os.path.exists(out_vocal_wav) and os.path.getsize(out_vocal_wav) > 1000)
        ok_beat = (not out_beat_wav) or (os.path.exists(out_beat_wav) and os.path.getsize(out_beat_wav) > 1000)
        return ok_vocal and ok_beat
    except Exception:
        return False
    finally:
        shutil.rmtree(temp_out_dir, ignore_errors=True)


def separate_audio_To_beat_or_vocal(input_path: str, mode: str, output_path: str,
                                    ffmpeg_dir: str = None, progress_callback=None) -> str:
    ffmpeg_exe = _get_ffmpeg_exe(ffmpeg_dir)
    creationflags = 0x08000000 if os.name == 'nt' else 0
    is_mp3_out = output_path.lower().endswith(".mp3")

    temp_vocal = os.path.splitext(output_path)[0] + "_tmp_demucs_vocal.wav"
    temp_beat = os.path.splitext(output_path)[0] + "_tmp_demucs_beat.wav"

    try:
        need_vocal = temp_vocal if mode == "vocal" else None
        need_beat = temp_beat if mode == "beat" else None
        if _try_demucs_separation(input_path, need_vocal, need_beat, ffmpeg_dir=ffmpeg_dir, progress_callback=progress_callback):
            src_wav = temp_vocal if mode == "vocal" else temp_beat
            if os.path.exists(src_wav):
                if is_mp3_out:
                    cmd_conv = [
                        ffmpeg_exe, '-y', '-i', src_wav,
                        '-vn', '-acodec', 'libmp3lame', '-q:a', '2', output_path
                    ]
                    subprocess.run(cmd_conv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=creationflags)
                else:
                    shutil.move(src_wav, output_path)
                if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                    return output_path

        if mode == "beat":
            if progress_callback:
                progress_callback(35, "Đang tách nhạc Beat và khử lời hát (Multi-Band Vocal Cancellation DSP)...")
            beat_filter = (
                "[0:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,asplit=2[a_low][a_mid];"
                "[a_low]lowpass=f=115,volume=1.25[bass];"
                "[a_mid]highpass=f=115,pan=stereo|c0=c0-c1|c1=c1-c0,volume=1.45[side];"
                "[bass][side]amix=inputs=2:duration=first:dropout_transition=2,alimiter=limit=0.95[outa]"
            )
            cmd = [
                ffmpeg_exe, '-y', '-i', input_path, '-vn',
                '-filter_complex', beat_filter,
                '-map', '[outa]'
            ]
            if is_mp3_out:
                cmd.extend(['-acodec', 'libmp3lame', '-q:a', '2', output_path])
            else:
                cmd.extend(['-acodec', 'pcm_s16le', '-ar', '44100', '-ac', '2', output_path])

            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 creationflags=creationflags, timeout=240)
            if res.returncode != 0:
                cmd_fb = [
                    ffmpeg_exe, '-y', '-i', input_path, '-vn',
                    '-af', 'stereotools=mlev=0.03:slev=1.6,equalizer=f=1000:t=q:w=1.2:g=-15,equalizer=f=2500:t=q:w=1.2:g=-15',
                    '-acodec', 'libmp3lame' if is_mp3_out else 'pcm_s16le',
                    output_path
                ]
                subprocess.run(cmd_fb, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               creationflags=creationflags, timeout=180)

        else:
            if progress_callback:
                progress_callback(35, "Đang tách riêng Giọng hát và lọc bỏ nhạc nền (Center-Vocal Isolation DSP)...")
            vocal_filter = (
                "stereotools=mlev=1.5:slev=0.18,"
                "highpass=f=90,lowpass=f=7800,"
                "dynaudnorm=f=150:g=13:p=0.92:m=7.0"
            )
            cmd = [ffmpeg_exe, '-y', '-i', input_path, '-vn', '-af', vocal_filter]
            if is_mp3_out:
                cmd.extend(['-acodec', 'libmp3lame', '-q:a', '2', output_path])
            else:
                cmd.extend(['-acodec', 'pcm_s16le', '-ar', '16000', '-ac', '1', output_path])

            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 creationflags=creationflags, timeout=240)
            if res.returncode != 0:
                cmd_fb = [
                    ffmpeg_exe, '-y', '-i', input_path, '-vn',
                    '-af', 'highpass=f=90,lowpass=f=7800,dynaudnorm=f=150:g=13:p=0.92:m=7.0',
                    '-acodec', 'libmp3lame' if is_mp3_out else 'pcm_s16le',
                    '-ar', '44100' if is_mp3_out else '16000',
                    '-ac', '2' if is_mp3_out else '1',
                    output_path
                ]
                subprocess.run(cmd_fb, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               creationflags=creationflags, timeout=180)

        return output_path
    finally:
        for tmp_f in (temp_vocal, temp_beat):
            if os.path.exists(tmp_f):
                try:
                    os.remove(tmp_f)
                except Exception:
                    pass


def _phonetic_skeleton_vi(text: str) -> str:
    if not text:
        return ""
    s = text.lower().strip()
    s = s.replace("đ", "d")
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = re.sub(r"[^\w\s]", " ", s)

    tokens = s.split()
    norm_tokens = []
    for tok in tokens:
        t = tok
        t = re.sub(r"^(tr|ch)", "c_", t)
        t = re.sub(r"^(s|x)", "s_", t)
        t = re.sub(r"^(d|gi|r|v)", "z_", t)
        t = re.sub(r"^(k|q|c)(?!_)", "k_", t)
        t = re.sub(r"^(ng|ngh)", "ng_", t)
        t = re.sub(r"^(g|gh)", "g_", t)
        t = re.sub(r"^(n|l)", "n_", t)
        t = t.replace("y", "i")
        t = re.sub(r"(ng|nh|n|m)$", "N", t)
        t = re.sub(r"(ch|c|t|p)$", "T", t)
        norm_tokens.append(t)

    return " ".join(norm_tokens)


def _extract_clean_lyrics_from_description(description: str) -> list:
    if not description or len(description.strip()) < 30:
        return []

    ignore_keywords = (
        "http://", "https://", "www.", ".com", ".vn", "youtu.be",
        "subscribe", "đăng ký kênh", "copyright", "bản quyền", "all rights",
        "composer", "producer", "executive", "mix & master", "mixed by", "mastered by",
        "director", "editor", "artwork", "graphic design", "follow me", "contact",
        "booking", "spotify", "apple music", "sound engineer", "recording studio"
    )

    candidate_lines = []
    for raw_line in description.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^\[?[A-Za-z0-9\s]+\]\s*", "", line).strip()
        line = re.sub(r"^\d{1,2}:\d{2}(:\d{2})?\s*[-–—]?\s*", "", line).strip()
        line_no_adlib = re.sub(r"\([^\)]*\)", "", line).strip()
        if line_no_adlib:
            line = line_no_adlib

        if not line or line.startswith("#") or line.startswith("@"):
            continue

        lower_l = line.lower()
        if any(kw in lower_l for kw in ignore_keywords):
            continue
        if ":" in line and len(line.split(":")[0].split()) <= 3:
            continue

        words = line.split()
        if 2 <= len(words) <= 22:
            alpha_cnt = sum(1 for c in line if c.isalpha())
            if alpha_cnt >= len(line) * 0.60:
                candidate_lines.append(line)

    if len(candidate_lines) >= 5:
        return candidate_lines
    return []


def _fetch_lrclib_plain_lyrics_only(track_title: str) -> list:
    if not track_title:
        return []

    clean_q = re.sub(r"\(.*?\)|\[.*?\]", " ", track_title)
    clean_q = re.sub(
        r"(?i)\b(official|visualizer|music\s+video|mv|lyrics?|video|audio|prod\.?|ft\.?|feat\.?|remake|remix|version|ver)\b.*",
        " ",
        clean_q
    )
    clean_q = re.sub(r"[｜|\-–—_]+", " ", clean_q)
    clean_q = re.sub(r"\s+", " ", clean_q).strip()
    if len(clean_q) < 3:
        return []

    try:
        resp = requests.get(
            "https://lrclib.net/api/search",
            params={"q": clean_q},
            headers={"User-Agent": "yftipDownloader/2.0"},
            timeout=4
        )
        if resp.status_code != 200:
            return []

        results = resp.json()
        if not isinstance(results, list) or not results:
            return []

        best_item = results[0]
        plain_lines = []
        plain_raw = best_item.get("plainLyrics") or ""
        for l in plain_raw.splitlines():
            l_clean = l.strip()
            if l_clean and len(l_clean.split()) >= 2:
                plain_lines.append(l_clean)

        return plain_lines
    except Exception:
        return []


def align_segments_with_reference_lyrics(segments: list, reference_lines: list) -> list:
    if not segments or not reference_lines:
        return segments

    ref_entries = []
    for line in reference_lines:
        clean_l = _clean_caption_artifacts(line)
        if clean_l and len(clean_l.split()) >= 2:
            words_l = clean_l.split()
            ref_entries.append({
                'text': clean_l,
                'words': words_l,
                'phonetic': _phonetic_skeleton_vi(clean_l),
                'word_count': len(words_l)
            })

    if not ref_entries:
        return segments

    aligned = []
    n_segs = len(segments)

    for idx_s, seg in enumerate(segments):
        s_txt = seg['text'].strip()
        s_phon = _phonetic_skeleton_vi(s_txt)
        s_words = s_txt.split()
        s_wc = len(s_words)
        next_start = segments[idx_s + 1]['start'] if idx_s + 1 < n_segs else seg['end'] + 4.0
        avail_window = next_start - seg['start']

        best_ref_text = None
        best_score = 0.0

        for ref in ref_entries:
            r_wc = ref['word_count']
            if abs(r_wc - s_wc) <= 2 and s_wc >= 4:
                phon_sim = difflib.SequenceMatcher(None, s_phon, ref['phonetic']).ratio()
                raw_sim = difflib.SequenceMatcher(None, s_txt.lower(), ref['text'].lower()).ratio()
                comb = phon_sim * 0.60 + raw_sim * 0.40
                if comb > best_score and comb >= 0.68:
                    best_score = comb
                    best_ref_text = ref['text']

            elif 3 <= s_wc < r_wc <= s_wc + 6 and avail_window >= 2.8:
                ref_prefix_words = ref['words'][:s_wc]
                ref_prefix_phon = _phonetic_skeleton_vi(" ".join(ref_prefix_words))
                prefix_sim = difflib.SequenceMatcher(None, s_phon, ref_prefix_phon).ratio()
                if prefix_sim >= 0.80 and prefix_sim > best_score:
                    ref_tail_phon = _phonetic_skeleton_vi(" ".join(ref['words'][s_wc:]))
                    next_txt_phon = _phonetic_skeleton_vi(segments[idx_s + 1]['text']) if idx_s + 1 < n_segs else ""
                    if not next_txt_phon or difflib.SequenceMatcher(None, ref_tail_phon, next_txt_phon).ratio() < 0.50:
                        best_score = prefix_sim
                        best_ref_text = ref['text']

        if best_ref_text:
            aligned.append({
                'start': seg['start'],
                'end': seg['end'],
                'text': best_ref_text
            })
        else:
            aligned.append(seg)

    return aligned


def recover_half_sentences_across_song(segments: list) -> list:
    if not segments or len(segments) < 4:
        return segments

    recovered = [dict(s) for s in segments]
    n = len(recovered)

    templates = []
    for seg in recovered:
        w_list = seg['text'].split()
        if 6 <= len(w_list) <= 14 and _lexical_plausibility_score(seg['text']) >= 1.5:
            templates.append({
                'text': seg['text'],
                'words': w_list,
                'phon': _phonetic_skeleton_vi(seg['text']),
                'wc': len(w_list),
                'score': _lexical_plausibility_score(seg['text'])
            })

    if not templates:
        return recovered

    for i in range(n):
        curr = recovered[i]
        c_words = curr['text'].split()
        c_wc = len(c_words)
        if c_wc < 3 or c_wc > 7:
            continue

        c_phon = _phonetic_skeleton_vi(curr['text'])
        next_start = recovered[i + 1]['start'] if i + 1 < n else curr['end'] + 4.0
        avail_dur = next_start - curr['start']

        if avail_dur < 2.2:
            continue

        best_full_text = None
        best_match_score = 0.0

        for tpl in templates:
            if tpl['wc'] <= c_wc + 1 or tpl['wc'] > c_wc + 6:
                continue

            tpl_prefix_phon = _phonetic_skeleton_vi(" ".join(tpl['words'][:c_wc]))
            pref_sim = difflib.SequenceMatcher(None, c_phon, tpl_prefix_phon).ratio()

            if pref_sim >= 0.82:
                tpl_tail_phon = _phonetic_skeleton_vi(" ".join(tpl['words'][c_wc:]))
                next_phon = _phonetic_skeleton_vi(recovered[i + 1]['text']) if i + 1 < n else ""
                if not next_phon or difflib.SequenceMatcher(None, tpl_tail_phon[:len(next_phon)], next_phon).ratio() < 0.55:
                    if pref_sim > best_match_score:
                        best_match_score = pref_sim
                        best_full_text = tpl['text']

        if best_full_text:
            curr['text'] = best_full_text
            curr['end'] = round(min(next_start - 0.1, max(curr['end'], curr['start'] + 2.5)), 3)

    return recovered


def format_srt_time(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    ms = int(round((seconds % 1) * 1000))
    total_sec = int(math.floor(seconds))
    if ms >= 1000:
        ms -= 1000
        total_sec += 1
    m, s = divmod(total_sec, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_srt_time_to_seconds(time_str: str) -> float:
    try:
        time_str = time_str.strip().replace('.', ',')
        hms, ms = time_str.split(',')
        h, m, s = [int(x) for x in hms.split(':')]
        return h * 3600 + m * 60 + s + int(ms[:3].ljust(3, '0')) / 1000.0
    except Exception:
        return 0.0


def get_wav_duration_seconds(wav_path: str) -> float:
    try:
        with wave.open(wav_path, 'rb') as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            if rate > 0:
                return float(frames) / float(rate)
    except Exception:
        pass
    return 0.0


def _norm_word(word: str) -> str:
    return re.sub(r"^[^\w]+|[^\w]+$", "", word.lower(), flags=re.UNICODE)


def _clean_caption_artifacts(text: str) -> str:
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\{\\an\d+\}", " ", text)
    text = re.sub(r"\[[^\]]*\]", " ", text)
    text = re.sub(
        r"\([^\)]*\)",
        lambda m: " " if any(
            k in m.group(0).lower() for k in (
                "ca hát", "âm nhạc", "nhạc", "music", "singing", "applause", "vỗ tay", "cười", "sigh"
            )
        ) else m.group(0),
        text
    )
    text = re.sub(r"(?:^|\s)>>+\s*", " ", text)
    text = re.sub(r"[♪♫♬♩]+", " ", text)
    text = re.sub(r"\s+\b(oh\s+oh(\s+oh)?|ơ\s+ơ)\b\.?$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def apply_contextual_collocation_repairs(text: str) -> str:
    if not text:
        return ""
    fixed = text
    for pattern, replacement in CONTEXTUAL_COLLOCATION_FIXES_VI:
        def _repl(match):
            orig = match.group(0)
            if orig and orig[0].isupper():
                return replacement[0].upper() + replacement[1:]
            return replacement
        fixed = re.sub(pattern, _repl, fixed, flags=re.IGNORECASE)
    return fixed


def _remove_rolling_word_overlap(prev_text: str, curr_text: str) -> str:
    if not prev_text or not curr_text:
        return curr_text

    prev_words = prev_text.split()
    curr_words = curr_text.split()
    if not prev_words or not curr_words:
        return curr_text

    norm_prev = [_norm_word(w) for w in prev_words]
    norm_curr = [_norm_word(w) for w in curr_words]

    joined_prev = " ".join(w for w in norm_prev if w)
    joined_curr = " ".join(w for w in norm_curr if w)
    if joined_curr and joined_curr == joined_prev:
        return ""

    max_k = min(len(norm_prev), len(norm_curr))
    best_k = 0
    for k in range(max_k, 0, -1):
        if norm_prev[-k:] == norm_curr[:k]:
            if k >= 2 or (k == 1 and len(norm_curr[0]) >= 4 and not prev_words[-1].endswith(('.', '!', '?'))):
                best_k = k
                break

    if best_k > 0:
        return " ".join(curr_words[best_k:]).strip()

    return curr_text


def split_internal_capitalized_clauses(segments: list) -> list:
    if not segments:
        return []

    expanded = []
    for seg in segments:
        text = seg.get('text', '').strip()
        start = float(seg.get('start', 0.0))
        end = float(seg.get('end', 0.0))
        seg_words_meta = seg.get('words') or []
        words = text.split()
        if len(words) < 5 or end <= start:
            expanded.append({'start': start, 'end': end, 'text': text})
            continue

        has_exact_word_times = (len(seg_words_meta) == len(words))

        clauses = []
        curr_clause = [words[0]]
        curr_c_start = float(seg_words_meta[0]['start']) if has_exact_word_times else start

        for i in range(1, len(words)):
            w = words[i]
            prev_w = words[i - 1]
            w_clean = _norm_word(w)
            prev_clean = _norm_word(prev_w)

            is_cap = len(w) > 0 and w[0].isupper() and not w.isupper()
            prev_ends_punct = prev_w.endswith(('.', '!', '?'))
            prev_ends_comma = prev_w.endswith((',', ';', ':'))
            prev_is_dangling = prev_clean in DANGLING_END_WORDS_ALL
            is_compound_pair = (prev_clean, w_clean) in SPLIT_COMPOUND_PAIRS_VI
            remaining_words_count = len(words) - i

            word_gap = 0.0
            if has_exact_word_times:
                word_gap = max(0.0, float(seg_words_meta[i]['start']) - float(seg_words_meta[i - 1]['end']))

            should_split_here = False
            if prev_ends_punct and len(curr_clause) >= 3 and remaining_words_count >= 3:
                should_split_here = True
            elif has_exact_word_times and word_gap >= 0.65 and len(curr_clause) >= 3 and remaining_words_count >= 3 and not prev_is_dangling:
                should_split_here = True
            elif is_cap and not prev_is_dangling and not is_compound_pair and remaining_words_count >= 3:
                if w_clean in SENTENCE_STARTER_WORDS_ALL and len(curr_clause) >= 4:
                    should_split_here = True
                elif len(curr_clause) >= 6:
                    should_split_here = True
            elif prev_ends_comma and len(curr_clause) >= 7 and remaining_words_count >= 4 and not prev_is_dangling:
                should_split_here = True
            elif len(curr_clause) >= 12 and w_clean in SENTENCE_STARTER_WORDS_ALL and not prev_is_dangling and remaining_words_count >= 3:
                should_split_here = True
            elif len(curr_clause) >= 14 and not prev_is_dangling and not is_compound_pair and remaining_words_count >= 3:
                should_split_here = True

            if should_split_here:
                c_end_t = float(seg_words_meta[i - 1]['end']) if has_exact_word_times else None
                clauses.append({
                    'text': " ".join(curr_clause).strip(),
                    'start': curr_c_start,
                    'end': c_end_t
                })
                curr_clause = [w]
                curr_c_start = float(seg_words_meta[i]['start']) if has_exact_word_times else None
            else:
                curr_clause.append(w)

        if curr_clause:
            if clauses and len(curr_clause) <= 2:
                clauses[-1]['text'] = (clauses[-1]['text'] + " " + " ".join(curr_clause)).strip()
                clauses[-1]['end'] = float(seg_words_meta[-1]['end']) if has_exact_word_times else end
            else:
                clauses.append({
                    'text': " ".join(curr_clause).strip(),
                    'start': curr_c_start,
                    'end': float(seg_words_meta[-1]['end']) if has_exact_word_times else end
                })

        if len(clauses) == 1:
            expanded.append({'start': start, 'end': end, 'text': clauses[0]['text']})
        elif has_exact_word_times:
            for c_item in clauses:
                s_t = max(start, c_item['start'] if c_item['start'] is not None else start)
                e_t = max(s_t + 0.35, c_item['end'] if c_item['end'] is not None else end)
                expanded.append({
                    'start': round(s_t, 3),
                    'end': round(e_t, 3),
                    'text': c_item['text']
                })
        else:
            total_chars = max(1, sum(len(c['text']) for c in clauses))
            total_dur = max(0.4, end - start)
            cur_t = start
            for idx_c, c_item in enumerate(clauses):
                c_text = c_item['text']
                c_dur = total_dur * (len(c_text) / total_chars)
                c_end = end if idx_c == len(clauses) - 1 else round(cur_t + c_dur, 3)
                expanded.append({
                    'start': round(cur_t, 3),
                    'end': round(c_end, 3),
                    'text': c_text
                })
                cur_t = c_end

    return expanded


def _lexical_plausibility_score(text: str) -> float:
    if not text or is_hallucination_text(text):
        return -50.0
    words = text.split()
    if not words:
        return -50.0

    lower_words = [_norm_word(w) for w in words if _norm_word(w)]
    if not lower_words:
        return -50.0

    score = 0.0
    wc = len(lower_words)
    if 5 <= wc <= 12:
        score += 2.5
    elif 3 <= wc <= 4:
        score += 0.5
    elif wc <= 2:
        score -= 2.0

    if lower_words[-1] in DANGLING_END_WORDS_ALL:
        score -= 3.5

    for i in range(len(lower_words) - 1):
        bg = (lower_words[i], lower_words[i + 1])
        if bg in SPLIT_COMPOUND_PAIRS_VI:
            score += 2.8
        if bg in NONSENSE_BIGRAMS_VI:
            score -= 4.5

    unique_ratio = len(set(lower_words)) / len(lower_words)
    if wc >= 4 and unique_ratio < 0.45:
        score -= 5.0

    if text[-1] in ('.', '!', '?'):
        score += 0.3
    return score


def fix_enjambment_and_sentence_boundaries(segments: list) -> list:
    if not segments:
        return []

    items = []
    for s in sorted(segments, key=lambda x: x.get('start', 0.0)):
        txt = _clean_caption_artifacts(s.get('text', ''))
        txt = clean_intra_segment_repetition(txt, max_allowed=2)
        txt = apply_contextual_collocation_repairs(txt)
        start = float(s.get('start', 0.0))
        end = float(s.get('end', 0.0))
        if txt and end > start and not is_hallucination_text(txt):
            item_dict = {'start': start, 'end': end, 'text': txt}
            if s.get('words'):
                item_dict['words'] = s['words']
            items.append(item_dict)

    if not items:
        return []

    for i in range(len(items) - 1):
        curr = items[i]
        nxt = items[i + 1]
        if nxt['start'] - curr['end'] > 1.2:
            continue
        c_words = curr['text'].split()
        n_words = nxt['text'].split()
        if len(c_words) >= 3 and n_words:
            last_w = c_words[-1]
            last_norm = _norm_word(last_w)
            if not last_w.endswith(('.', '!', '?')) and (
                (last_w[0].isupper() and len(c_words) >= 3) or last_norm in {"phá", "ta", "vậy", "dẫu", "nhưng", "vì", "dòng", "trái", "lúc"}
            ):
                if last_norm == "lúc" and _norm_word(n_words[0]) != "ấy":
                    curr['text'] = apply_contextual_collocation_repairs(curr['text'] + " ấy")
                else:
                    curr['text'] = " ".join(c_words[:-1]).strip()
                    curr.pop('words', None)
                    if len(n_words[0]) > 1 and n_words[0][0].isupper():
                        n_words[0] = n_words[0][0].lower() + n_words[0][1:]
                    nxt['text'] = apply_contextual_collocation_repairs((last_w + " " + " ".join(n_words)).strip())
                    nxt.pop('words', None)

    deduped = []
    for seg in items:
        seg['text'] = apply_contextual_collocation_repairs(seg['text'])
        if deduped:
            prev = deduped[-1]
            if seg['start'] - prev['end'] < 2.0:
                trimmed = _remove_rolling_word_overlap(prev['text'], seg['text'])
                if not trimmed:
                    prev['end'] = max(prev['end'], seg['end'])
                    continue
                if trimmed != seg['text']:
                    seg.pop('words', None)
                seg['text'] = apply_contextual_collocation_repairs(trimmed)
        if seg['text'] and not is_hallucination_text(seg['text']):
            deduped.append(seg)

    merged_connected = []
    i = 0
    while i < len(deduped):
        curr = dict(deduped[i])
        while i + 1 < len(deduped):
            nxt = deduped[i + 1]
            gap = nxt['start'] - curr['end']
            c_words = curr['text'].split()
            n_words = nxt['text'].split()
            if not c_words or not n_words or gap > 0.75:
                break

            last_c = _norm_word(c_words[-1])
            first_n = _norm_word(n_words[0])
            is_split_compound = (last_c, first_n) in SPLIT_COMPOUND_PAIRS_VI
            is_dangling_tail = last_c in DANGLING_END_WORDS_ALL

            should_join = False
            if not curr['text'].endswith(('.', '!', '?')) and len(c_words) + len(n_words) <= 12:
                if is_split_compound or is_dangling_tail or len(n_words) <= 2 or len(c_words) <= 2:
                    should_join = True

            if should_join:
                nxt_txt = nxt['text']
                if len(nxt_txt) > 1 and nxt_txt[0].isupper() and (is_split_compound or is_dangling_tail or len(n_words) <= 2):
                    nxt_txt = nxt_txt[0].lower() + nxt_txt[1:]
                curr['text'] = apply_contextual_collocation_repairs(f"{curr['text']} {nxt_txt}".strip())
                curr['end'] = nxt['end']
                curr.pop('words', None)
                i += 1
            else:
                break

        merged_connected.append(curr)
        i += 1

    split_caps = split_internal_capitalized_clauses(merged_connected)

    clean_ordered = []
    for seg in split_caps:
        txt = apply_contextual_collocation_repairs(clean_intra_segment_repetition(seg['text'], max_allowed=2))
        if not txt or is_hallucination_text(txt):
            continue

        words_chk = txt.split()
        norm_set = {_norm_word(w) for w in words_chk if _norm_word(w)}
        if not norm_set or norm_set.issubset({"oh", "o", "ố", "ồ", "út", "à", "ờ", "ừm", "ah", "yeah", "rồi", "thôi", "tay"}):
            if len(words_chk) <= 3 and not norm_set.issuperset({"đủ", "rồi"}):
                continue

        if len(txt) > 1 and txt[0].islower():
            txt = txt[0].upper() + txt[1:]

        if clean_ordered and (seg['start'] - clean_ordered[-1]['end']) < 2.5:
            prev_txt = clean_ordered[-1]['text']
            sim = difflib.SequenceMatcher(None, _phonetic_skeleton_vi(prev_txt), _phonetic_skeleton_vi(txt)).ratio()
            if sim >= 0.74:
                if len(txt.split()) >= len(prev_txt.split()) + 2:
                    clean_ordered[-1]['text'] = txt
                elif _lexical_plausibility_score(txt) > _lexical_plausibility_score(prev_txt) + 0.5:
                    clean_ordered[-1]['text'] = txt
                clean_ordered[-1]['end'] = max(clean_ordered[-1]['end'], seg['end'])
                continue

        s_time = max(0.0, seg['start'])
        max_reasonable_dur = max(3.2, len(words_chk) * 0.60 + 1.2)
        e_time = min(seg['end'], s_time + max_reasonable_dur)
        e_time = max(s_time + 0.35, e_time)

        if clean_ordered and s_time < clean_ordered[-1]['end']:
            clean_ordered[-1]['end'] = round(max(clean_ordered[-1]['start'] + 0.20, s_time), 3)
            s_time = max(s_time, clean_ordered[-1]['end'])
            e_time = max(s_time + 0.35, e_time)

        clean_ordered.append({
            'start': round(s_time, 3),
            'end': round(e_time, 3),
            'text': txt
        })

    return clean_ordered


def reconcile_and_fuse_subtitles(ai_segments: list, auto_segments: list) -> list:
    if not auto_segments:
        return fix_enjambment_and_sentence_boundaries(ai_segments)
    if not ai_segments:
        return fix_enjambment_and_sentence_boundaries(auto_segments)

    ai_clean = fix_enjambment_and_sentence_boundaries(ai_segments)
    auto_clean = fix_enjambment_and_sentence_boundaries(auto_segments)

    if not ai_clean:
        return auto_clean
    if not auto_clean:
        return ai_clean

    if len(ai_clean) <= 2 and len(auto_clean) > 6:
        return auto_clean

    merged = []
    fully_used_auto = set()

    for a_seg in ai_clean:
        a_start = float(a_seg['start'])
        a_end = float(a_seg['end'])
        a_dur = max(0.1, a_end - a_start)
        a_text = a_seg['text']
        a_wc = len(a_text.split())

        overlapping_autos = []
        for idx, au in enumerate(auto_clean):
            s_start = float(au['start'])
            s_end = float(au['end'])
            s_dur = max(0.1, s_end - s_start)
            overlap = min(a_end, s_end) - max(a_start, s_start)
            if overlap > 0.15 and (overlap / a_dur >= 0.30 or overlap / s_dur >= 0.30):
                overlapping_autos.append((idx, au, overlap / s_dur))

        if not overlapping_autos:
            merged.append({'start': a_start, 'end': a_end, 'text': a_text})
            continue

        for idx, _, cov_ratio in overlapping_autos:
            if cov_ratio >= 0.60:
                fully_used_auto.add(idx)

        combined_auto_text = ""
        for _, au, _ in overlapping_autos:
            s_clean_txt = au['text']
            if not combined_auto_text:
                combined_auto_text = s_clean_txt
            else:
                rem = _remove_rolling_word_overlap(combined_auto_text, s_clean_txt)
                if rem:
                    combined_auto_text = f"{combined_auto_text} {rem}".strip()

        combined_auto_text = apply_contextual_collocation_repairs(combined_auto_text)
        auto_wc = len(combined_auto_text.split())

        score_a = _lexical_plausibility_score(a_text)
        score_au = _lexical_plausibility_score(combined_auto_text)

        chosen_text = a_text
        if auto_wc >= a_wc + 3 and auto_wc <= 15 and score_au >= score_a - 0.5:
            chosen_text = combined_auto_text
        elif score_au > score_a + 1.0 and abs(auto_wc - a_wc) <= 2:
            chosen_text = combined_auto_text

        merged.append({
            'start': a_start,
            'end': a_end,
            'text': chosen_text
        })

    for idx, au in enumerate(auto_clean):
        if idx in fully_used_auto:
            continue
        s_start = float(au['start'])
        s_end = float(au['end'])
        s_dur = max(0.1, s_end - s_start)
        s_text = au['text']
        if not s_text or is_hallucination_text(s_text):
            continue

        is_covered = False
        for m_seg in merged:
            overlap = min(m_seg['end'], s_end) - max(m_seg['start'], s_start)
            if overlap / s_dur >= 0.45:
                is_covered = True
                break
            if abs(m_seg['start'] - s_start) < 2.8 and is_similar(
                _phonetic_skeleton_vi(m_seg['text']), _phonetic_skeleton_vi(s_text), threshold=0.65
            ):
                is_covered = True
                break

        if not is_covered:
            merged.append({'start': s_start, 'end': s_end, 'text': s_text})

    merged.sort(key=lambda x: x['start'])
    return fix_enjambment_and_sentence_boundaries(merged)


def ai_semantic_global_review(segments: list, reference_lines: list = None, progress_callback=None) -> list:
    if not segments:
        return []

    reviewed = fix_enjambment_and_sentence_boundaries(segments)

    if reference_lines:
        reviewed = align_segments_with_reference_lyrics(reviewed, reference_lines)

    reviewed = recover_half_sentences_across_song(reviewed)

    n = len(reviewed)
    for i in range(n):
        for j in range(i + 1, n):
            if abs(reviewed[j]['start'] - reviewed[i]['start']) < 10.0:
                continue
            t_i = reviewed[i]['text']
            t_j = reviewed[j]['text']
            wc_i = len(t_i.split())
            wc_j = len(t_j.split())
            if abs(wc_i - wc_j) > 3:
                continue

            phon_i = _phonetic_skeleton_vi(t_i)
            phon_j = _phonetic_skeleton_vi(t_j)
            phon_sim = difflib.SequenceMatcher(None, phon_i, phon_j).ratio()

            if 0.66 <= phon_sim < 0.99:
                score_i = _lexical_plausibility_score(t_i) + (0.4 if wc_i > wc_j else 0.0)
                score_j = _lexical_plausibility_score(t_j) + (0.4 if wc_j > wc_i else 0.0)
                if score_i > score_j + 0.2:
                    reviewed[j]['text'] = t_i
                elif score_j > score_i + 0.2:
                    reviewed[i]['text'] = t_j

    #Tính năng AI - Hãy điền api_key
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if api_key and len(reviewed) <= 140:
        try:
            if progress_callback:
                progress_callback(96, "AI Reviewer: Đang đánh giá tổng thể ngữ nghĩa và khôi phục câu toàn bài...")
            numbered_lines = "\n".join(f"{idx}: {s['text']}" for idx, s in enumerate(reviewed))
            prompt = (
                "Bạn là chuyên gia hiệu đính phụ đề bài hát/video Tiếng Việt và Tiếng Anh.\n"
                "Hãy sửa các từ bị nhận diện sai âm vị, khôi phục các từ bị thiếu ở cuối câu và sửa lỗi chính tả "
                "trong danh sách câu dưới đây sao cho đúng ngữ cảnh tự nhiên nhất, GIỮ NGUYÊN số thứ tự dòng (0, 1, 2...) "
                "và không thêm/bớt dòng:\n\n" + numbered_lines
            )
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
            resp = requests.post(
                url,
                json={"contents": [{"parts": [{"text": prompt}]}]},
                timeout=15
            )
            if resp.status_code == 200:
                data = resp.json()
                out_text = data["candidates"][0]["content"]["parts"][0]["text"]
                for line in out_text.splitlines():
                    m = re.match(r"^(\d+)\s*:\s*(.+)$", line.strip())
                    if m:
                        idx_line = int(m.group(1))
                        new_txt = m.group(2).strip()
                        if 0 <= idx_line < len(reviewed) and new_txt:
                            reviewed[idx_line]['text'] = new_txt
        except Exception:
            pass

    return fix_enjambment_and_sentence_boundaries(reviewed)


def parse_srt_file_to_segments(srt_path: str) -> list:
    if not srt_path or not os.path.exists(srt_path):
        return []

    try:
        with open(srt_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception:
        return []

    blocks = re.split(r"\n\s*\n", content.strip())
    raw_items = []
    for block in blocks:
        lines = [line.strip() for line in block.strip().splitlines() if line.strip()]
        if len(lines) < 2:
            continue
        time_line_idx = -1
        for idx, l in enumerate(lines):
            if "-->" in l:
                time_line_idx = idx
                break
        if time_line_idx == -1 or time_line_idx + 1 >= len(lines):
            continue

        parts = lines[time_line_idx].split("-->")
        start_s = parse_srt_time_to_seconds(parts[0])
        end_s = parse_srt_time_to_seconds(parts[1].split()[0])
        text = " ".join(lines[time_line_idx + 1:]).strip()
        text = apply_contextual_collocation_repairs(_clean_caption_artifacts(text))

        if end_s > start_s and text and not is_hallucination_text(text):
            raw_items.append({'start': start_s, 'end': end_s, 'text': text})

    return raw_items


def clean_downloaded_srt(srt_path: str):
    if not os.path.exists(srt_path):
        return
    try:
        raw_segs = parse_srt_file_to_segments(srt_path)
        cleaned_segs = fix_enjambment_and_sentence_boundaries(raw_segs)
        if cleaned_segs:
            write_srt_file(cleaned_segs, srt_path)
    except Exception:
        pass


def fetch_platform_subtitles_and_metadata(url: str, video_path: str, language: str = "auto",
                                          ffmpeg_dir: str = None, allow_auto: bool = False,
                                          progress_callback=None) -> tuple:
    base_title = os.path.splitext(os.path.basename(video_path))[0]
    lrc_plain_lines = _fetch_lrclib_plain_lyrics_only(base_title)

    if not url:
        return None, None, None, lrc_plain_lines

    def emit(percent, msg):
        if progress_callback:
            try:
                progress_callback(percent, msg)
            except TypeError:
                progress_callback(f"{msg} ({percent}%)")

    try:
        import yt_dlp
        emit(4, "Đang kiểm tra phụ đề & trích xuất dữ liệu lời bài hát chuẩn từ nền tảng...")

        ydl_check_opts = {
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
        }
        with yt_dlp.YoutubeDL(ydl_check_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if 'entries' in info and info['entries']:
                info = info['entries'][0]

            vid_title = info.get('title') or base_title
            vid_desc = info.get('description') or ""

            desc_lyrics = _extract_clean_lyrics_from_description(vid_desc)
            if not lrc_plain_lines and vid_title != base_title:
                lrc_plain_lines = _fetch_lrclib_plain_lyrics_only(vid_title)

            reference_lines = desc_lyrics if len(desc_lyrics) >= 6 else lrc_plain_lines

            manual_subs = info.get('subtitles') or {}
            auto_subs = info.get('automatic_captions') or {}

            lang_pref = (language or "auto").lower()
            if lang_pref == "vi":
                priority_prefixes = ['vi']
            elif lang_pref == "en":
                priority_prefixes = ['en']
            else:
                orig_lang = str(info.get('language') or '').lower()
                if orig_lang.startswith('en'):
                    priority_prefixes = ['en', 'vi']
                else:
                    priority_prefixes = ['vi', 'en']

            def _find_lang_key(sub_dict: dict):
                if not sub_dict:
                    return None
                for prefix in priority_prefixes:
                    for k in sub_dict.keys():
                        kl = k.lower()
                        if kl == f"{prefix}-orig" and sub_dict[k]:
                            return k
                    for k in sub_dict.keys():
                        kl = k.lower()
                        if (kl == prefix or kl.startswith(prefix + '-') or kl.startswith(prefix + '_')) and sub_dict[k]:
                            return k
                return None

            matched_manual = _find_lang_key(manual_subs)
            if matched_manual:
                emit(30, f"Phát hiện phụ đề chuẩn làm sẵn ({matched_manual})! Đang tải trực tiếp...")
                base_no_ext = os.path.splitext(video_path)[0]
                target_srt = base_no_ext + ".srt"
                temp_outtmpl = base_no_ext + "_manualsub.%(ext)s"

                dl_opts = {
                    'noplaylist': True,
                    'quiet': True,
                    'no_warnings': True,
                    'skip_download': True,
                    'writesubtitles': True,
                    'writeautomaticsub': False,
                    'subtitleslangs': [matched_manual],
                    'subtitlesformat': 'srt/vtt/best',
                    'outtmpl': temp_outtmpl,
                    'postprocessors': [{'key': 'FFmpegSubtitlesConvertor', 'format': 'srt'}],
                }
                if ffmpeg_dir:
                    dl_opts['ffmpeg_location'] = ffmpeg_dir

                with yt_dlp.YoutubeDL(dl_opts) as ydl_sub:
                    ydl_sub.download([url])

                candidates = glob.glob(glob.escape(base_no_ext) + "_manualsub*.srt")
                if candidates:
                    if os.path.exists(target_srt):
                        try:
                            os.remove(target_srt)
                        except Exception:
                            pass
                    os.replace(candidates[0], target_srt)
                    for leftover in glob.glob(glob.escape(base_no_ext) + "_manualsub*"):
                        try:
                            os.remove(leftover)
                        except Exception:
                            pass
                    clean_downloaded_srt(target_srt)
                    if os.path.exists(target_srt) and os.path.getsize(target_srt) > 10:
                        lang_short = 'en' if matched_manual.lower().startswith('en') else 'vi'
                        emit(100, f"Đã tải và chuẩn hóa hoàn tất phụ đề làm sẵn ({matched_manual})!")
                        return target_srt, 'manual', lang_short, reference_lines

            if allow_auto and auto_subs:
                matched_auto = _find_lang_key(auto_subs)
                if matched_auto:
                    emit(8, f"Đang tải phụ đề tự động của nền tảng ({matched_auto}) để đối chiếu từ vựng...")
                    base_no_ext = os.path.splitext(video_path)[0]
                    temp_outtmpl = base_no_ext + "_autosub_ref.%(ext)s"

                    dl_auto_opts = {
                        'noplaylist': True,
                        'quiet': True,
                        'no_warnings': True,
                        'skip_download': True,
                        'writesubtitles': False,
                        'writeautomaticsub': True,
                        'subtitleslangs': [matched_auto],
                        'subtitlesformat': 'srt/vtt/best',
                        'outtmpl': temp_outtmpl,
                        'postprocessors': [{'key': 'FFmpegSubtitlesConvertor', 'format': 'srt'}],
                    }
                    if ffmpeg_dir:
                        dl_auto_opts['ffmpeg_location'] = ffmpeg_dir

                    with yt_dlp.YoutubeDL(dl_auto_opts) as ydl_auto:
                        ydl_auto.download([url])

                    auto_candidates = glob.glob(glob.escape(base_no_ext) + "_autosub_ref*.srt")
                    auto_segments = []
                    if auto_candidates:
                        raw_auto = parse_srt_file_to_segments(auto_candidates[0])
                        auto_segments = fix_enjambment_and_sentence_boundaries(raw_auto)
                    for leftover in glob.glob(glob.escape(base_no_ext) + "_autosub_ref*"):
                        try:
                            os.remove(leftover)
                        except Exception:
                            pass

                    if auto_segments:
                        lang_short = 'en' if matched_auto.lower().startswith('en') else 'vi'
                        return auto_segments, 'auto', lang_short, reference_lines

            return None, None, None, reference_lines
    except Exception:
        pass

    return None, None, None, lrc_plain_lines


def preprocess_audio(video_path: str, ffmpeg_dir: str = None, vocal_enhance: bool = False) -> str:
    output_wav = os.path.splitext(video_path)[0] + "_temp_vocal_for_srt.wav"
    ffmpeg_exe = _get_ffmpeg_exe(ffmpeg_dir)
    creationflags = 0x08000000 if os.name == 'nt' else 0

    af_chain = "highpass=f=75,lowpass=f=7900,dynaudnorm=f=150:g=13:p=0.92:m=6.0" if vocal_enhance else "highpass=f=70"

    cmd_basic = [
        ffmpeg_exe, '-y',
        '-i', video_path,
        '-vn',
        '-af', af_chain,
        '-acodec', 'pcm_s16le',
        '-ar', '16000',
        '-ac', '1',
        output_wav
    ]
    try:
        res = subprocess.run(cmd_basic, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             creationflags=creationflags, timeout=180)
        if res.returncode != 0:
            subprocess.run(
                [ffmpeg_exe, '-y', '-i', video_path, '-vn', '-acodec', 'pcm_s16le', '-ar', '16000', '-ac', '1', output_wav],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=creationflags, timeout=180
            )
    except Exception:
        return video_path

    if os.path.exists(output_wav) and os.path.getsize(output_wav) > 0:
        return output_wav
    return video_path


def extract_audio_slice(audio_path: str, start_sec: float, duration_sec: float, ffmpeg_dir: str = None) -> str:
    ffmpeg_exe = _get_ffmpeg_exe(ffmpeg_dir)
    slice_wav = f"{os.path.splitext(audio_path)[0]}_slice_{int(start_sec)}_{int(duration_sec)}.wav"
    creationflags = 0x08000000 if os.name == 'nt' else 0

    cmd = [
        ffmpeg_exe, '-y',
        '-ss', f"{start_sec:.3f}",
        '-t', f"{duration_sec:.3f}",
        '-i', audio_path,
        '-af', 'highpass=f=90,lowpass=f=7800,dynaudnorm=f=120:g=11:p=0.92:m=8.0',
        '-acodec', 'pcm_s16le',
        '-ar', '16000',
        '-ac', '1',
        slice_wav
    ]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             creationflags=creationflags, timeout=45)
        if res.returncode == 0 and os.path.exists(slice_wav) and os.path.getsize(slice_wav) > 4000:
            return slice_wav
    except Exception:
        pass
    return None


def find_uncovered_time_gaps(segments: list, total_duration: float, min_gap_sec: float = 10.0) -> list:
    if total_duration <= 5.0:
        return []
    if not segments:
        return [(0.0, total_duration)]

    sorted_segs = sorted(segments, key=lambda x: x.get('start', 0.0))
    gaps = []

    first_start = float(sorted_segs[0].get('start', 0.0))
    if first_start >= min_gap_sec + 3.0:
        gaps.append((0.0, first_start))

    prev_end = float(sorted_segs[0].get('end', 0.0))
    for seg in sorted_segs[1:]:
        s_start = float(seg.get('start', 0.0))
        s_end = float(seg.get('end', 0.0))
        if s_start - prev_end >= min_gap_sec:
            gaps.append((prev_end, s_start))
        prev_end = max(prev_end, s_end)

    if total_duration - prev_end >= min_gap_sec:
        gaps.append((prev_end, total_duration))

    return gaps


def extract_30s_speech_probe(audio_path: str, ffmpeg_dir: str = None) -> str:
    ffmpeg_exe = _get_ffmpeg_exe(ffmpeg_dir)
    probe_wav = os.path.splitext(audio_path)[0] + "_probe30s.wav"
    creationflags = 0x08000000 if os.name == 'nt' else 0

    cmd = [
        ffmpeg_exe, '-y',
        '-i', audio_path,
        '-af', 'silenceremove=start_periods=1:start_silence=0.2:start_threshold=-50dB',
        '-t', '30',
        '-acodec', 'pcm_s16le',
        '-ar', '16000',
        '-ac', '1',
        probe_wav
    ]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             creationflags=creationflags, timeout=45)
        if res.returncode == 0 and os.path.exists(probe_wav) and os.path.getsize(probe_wav) > 8000:
            return probe_wav
    except Exception:
        pass
    return audio_path


def verify_language_two_pass(model, audio_path: str, ffmpeg_dir: str = None,
                             user_lang: str = "auto", platform_lang: str = None) -> tuple:
    if user_lang in ("vi", "en"):
        return user_lang, None

    probe_path = extract_30s_speech_probe(audio_path, ffmpeg_dir=ffmpeg_dir)
    try:
        segs_auto, info_auto = model.transcribe(
            probe_path,
            language=None,
            beam_size=5,
            vad_filter=False,
            condition_on_previous_text=False,
            no_speech_threshold=None
        )
        detected = getattr(info_auto, 'language', 'vi')
        prob = getattr(info_auto, 'language_probability', 0.0)

        if detected in ('vi', 'en') and prob >= 0.60:
            verified_lang = detected
        else:
            segs_vi, _ = model.transcribe(probe_path, language="vi", beam_size=3, vad_filter=False, condition_on_previous_text=False, no_speech_threshold=None)
            list_vi = list(segs_vi)
            score_vi = sum(getattr(s, 'avg_logprob', -1.5) for s in list_vi) / max(1, len(list_vi)) if list_vi else -9.0

            segs_en, _ = model.transcribe(probe_path, language="en", beam_size=3, vad_filter=False, condition_on_previous_text=False, no_speech_threshold=None)
            list_en = list(segs_en)
            score_en = sum(getattr(s, 'avg_logprob', -1.5) for s in list_en) / max(1, len(list_en)) if list_en else -9.0

            if score_vi >= score_en - 0.15:
                verified_lang = "vi"
            elif score_en > score_vi:
                verified_lang = "en"
            else:
                verified_lang = platform_lang if platform_lang in ("vi", "en") else "vi"

        return verified_lang, None

    except Exception:
        fallback = user_lang if user_lang in ("vi", "en") else (platform_lang if platform_lang in ("vi", "en") else "vi")
        return fallback, None
    finally:
        if probe_path != audio_path and os.path.exists(probe_path) and probe_path.endswith("_probe30s.wav"):
            try:
                os.remove(probe_path)
            except Exception:
                pass


def is_hallucination_text(text: str) -> bool:
    if not text or not text.strip():
        return True
    cleaned = text.strip()
    lower = cleaned.lower()

    for pattern in SUBTITLE_HALLUCINATION_PATTERNS:
        if re.search(pattern, lower):
            return True

    alpha_num = re.sub(r"[^\w\s]", "", lower, flags=re.UNICODE).strip()
    if not alpha_num:
        return True
    return False


def strip_hallucination_substrings(text: str) -> str:
    result = _clean_caption_artifacts(text)
    for p in HALLUCINATION_TAIL_STRIPS:
        result = re.sub(p, "", result, flags=re.IGNORECASE).strip()
    return result


def is_similar(text1: str, text2: str, threshold: float = 0.85) -> bool:
    t1 = text1.strip().lower()
    t2 = text2.strip().lower()
    if not t1 or not t2:
        return False
    if t1 == t2:
        return True
    return difflib.SequenceMatcher(None, t1, t2).ratio() >= threshold


def clean_intra_segment_repetition(text: str, max_allowed: int = 2) -> str:
    words = text.strip().split()
    if len(words) <= 2:
        return text.strip()

    cleaned_words = []
    prev_word = ""
    word_count = 0
    for w in words:
        w_lower = _norm_word(w)
        if w_lower and w_lower == prev_word:
            word_count += 1
            limit = 1 if w_lower in {"còn", "và", "thì", "là", "nhưng", "mà", "em", "anh", "ta", "tôi"} else max_allowed
            if word_count <= limit:
                cleaned_words.append(w)
        else:
            prev_word = w_lower
            word_count = 1
            cleaned_words.append(w)

    result_text = " ".join(cleaned_words)

    tokens = result_text.split()
    n = len(tokens)
    for phrase_len in range(6, 1, -1):
        if n >= phrase_len * 2:
            new_tokens = []
            idx = 0
            while idx < len(tokens):
                phrase = [_norm_word(t) for t in tokens[idx:idx + phrase_len]]
                if len(phrase) == phrase_len and all(phrase):
                    repeats = 1
                    next_idx = idx + phrase_len
                    while next_idx + phrase_len <= len(tokens):
                        next_phrase = [_norm_word(t) for t in tokens[next_idx:next_idx + phrase_len]]
                        if next_phrase == phrase:
                            repeats += 1
                            next_idx += phrase_len
                        else:
                            break
                    if repeats > 1:
                        keep_times = 1 if phrase_len >= 2 else min(repeats, max_allowed)
                        new_tokens.extend(tokens[idx:idx + phrase_len] * keep_times)
                        idx = next_idx
                        continue
                new_tokens.append(tokens[idx])
                idx += 1
            tokens = new_tokens

    return " ".join(tokens).strip()


def write_srt_file(segments: list, output_srt_path: str):
    with open(output_srt_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments):
            start_str = format_srt_time(seg['start'])
            end_str = format_srt_time(seg['end'])
            f.write(f"{i + 1}\n{start_str} --> {end_str}\n{seg['text']}\n\n")


def generate_subtitles(video_path: str, progress_callback=None, ffmpeg_dir: str = None,
                       language: str = "auto", model_size: str = "standard",
                       mode: str = "auto", source_url: str = None,
                       pre_isolated_vocal_path: str = None) -> str:
    def emit(percent, msg):
        if progress_callback:
            try:
                progress_callback(percent, msg)
            except TypeError:
                progress_callback(f"{msg} ({percent}%)")

    is_ultra = (str(model_size).lower() in ("ultra", "large-v2", "sieu_chuan"))
    actual_whisper_model = "large-v2" if is_ultra else "medium"

    platform_auto_segments = []
    platform_detected_lang = None
    reference_lyric_lines = []

    sub_data, sub_type, p_lang, reference_lyric_lines = fetch_platform_subtitles_and_metadata(
        url=source_url,
        video_path=video_path,
        language=language,
        ffmpeg_dir=ffmpeg_dir,
        allow_auto=True,
        progress_callback=progress_callback
    )
    if sub_type == 'manual' and isinstance(sub_data, str) and os.path.exists(sub_data):
        return sub_data
    elif sub_type == 'auto' and isinstance(sub_data, list):
        platform_auto_segments = sub_data
        platform_detected_lang = p_lang

    srt_path = os.path.splitext(video_path)[0] + ".srt"
    temp_wav = None
    lang_code = None if (not language or language.lower() in ("auto", "vi+en", "mixed", "all")) else language.lower()

    vocab_hint = None
    if reference_lyric_lines:
        vocab_hint = ", ".join(reference_lyric_lines[:8])[:200]

    try:
        if pre_isolated_vocal_path and os.path.exists(pre_isolated_vocal_path):
            emit(10, "Đang nạp luồng Giọng hát để nhận diện phụ đề .srt...")
            temp_wav = preprocess_audio(pre_isolated_vocal_path, ffmpeg_dir=ffmpeg_dir, vocal_enhance=True)
        else:
            emit(10, "Đang chuẩn hóa âm thanh 16kHz & nâng âm cuối câu...")
            temp_wav = preprocess_audio(video_path, ffmpeg_dir=ffmpeg_dir, vocal_enhance=True)

        audio_source = temp_wav if (temp_wav and os.path.exists(temp_wav)) else video_path
        exact_wav_dur = get_wav_duration_seconds(audio_source)
        cleaned_ai_segments = []

        use_faster_whisper = False
        try:
            from faster_whisper import WhisperModel
            use_faster_whisper = True
        except ImportError:
            use_faster_whisper = False

        if use_faster_whisper:
            cpu_threads = min(8, os.cpu_count() or 4)

            def _load_whisper_model(target_model: str, target_device: str, target_compute: str):
                try:
                    return WhisperModel(
                        target_model,
                        device=target_device,
                        compute_type=target_compute,
                        cpu_threads=cpu_threads
                    )
                except Exception:
                    if target_model != "medium":
                        emit(16, "Đang chuyển sang mô hình dự phòng độ ổn định cao (medium)...")
                        return WhisperModel(
                            "medium",
                            device=target_device,
                            compute_type=target_compute,
                            cpu_threads=cpu_threads
                        )
                    raise

            def _transcribe_pass(model, target_audio: str, target_lang: str, use_vad: bool,
                                 time_offset: float = 0.0, progress_range: tuple = (25, 75)) -> tuple:
                collected = []
                beam = 6 if is_ultra else 5
                best_of = 6 if is_ultra else 5

                transcribe_kwargs = dict(
                    language=target_lang,
                    task="transcribe",
                    beam_size=beam,
                    best_of=best_of,
                    vad_filter=use_vad,
                    word_timestamps=True,
                    condition_on_previous_text=False,
                    initial_prompt=vocab_hint,
                    no_speech_threshold=None,
                    compression_ratio_threshold=None,
                    log_prob_threshold=None,
                    temperature=[0.0, 0.2, 0.4],
                )
                if use_vad:
                    transcribe_kwargs["vad_parameters"] = dict(
                        threshold=0.10,
                        min_speech_duration_ms=80,
                        max_speech_duration_s=15,
                        min_silence_duration_ms=650,
                        speech_pad_ms=150
                    )

                try:
                    segments_gen, info = model.transcribe(target_audio, **transcribe_kwargs)
                except TypeError:
                    transcribe_kwargs["no_speech_threshold"] = 1.0
                    transcribe_kwargs["compression_ratio_threshold"] = 10.0
                    if use_vad and "max_speech_duration_s" in transcribe_kwargs.get("vad_parameters", {}):
                        transcribe_kwargs["vad_parameters"].pop("max_speech_duration_s", None)
                    segments_gen, info = model.transcribe(target_audio, **transcribe_kwargs)

                detected_lang = getattr(info, 'language', None)
                total_duration = max(1.0, exact_wav_dur or getattr(info, 'duration', 30.0) or 30.0)

                p_start, p_end = progress_range
                mode_label = "Siêu chuẩn" if is_ultra else "Tiêu chuẩn"
                for seg in segments_gen:
                    txt = _clean_caption_artifacts(seg.text)
                    if not txt or is_hallucination_text(txt):
                        continue

                    words_meta = []
                    if getattr(seg, 'words', None):
                        for w_obj in seg.words:
                            w_str = _clean_caption_artifacts(getattr(w_obj, 'word', ''))
                            if w_str:
                                words_meta.append({
                                    'word': w_str,
                                    'start': float(getattr(w_obj, 'start', seg.start)) + time_offset,
                                    'end': float(getattr(w_obj, 'end', seg.end)) + time_offset
                                })

                    if words_meta:
                        s_t = max(float(seg.start) + time_offset, words_meta[0]['start'])
                        e_t = max(s_t + 0.3, words_meta[-1]['end'])
                    else:
                        s_t = float(seg.start) + time_offset
                        e_t = float(seg.end) + time_offset

                    collected.append({
                        'start': s_t,
                        'end': e_t,
                        'text': txt,
                        'words': words_meta,
                        'no_speech_prob': getattr(seg, 'no_speech_prob', 0.0),
                        'avg_logprob': getattr(seg, 'avg_logprob', -0.4),
                        'compression_ratio': getattr(seg, 'compression_ratio', 1.0)
                    })
                    current_time = min(total_duration, e_t)
                    pct = min(99, int((current_time / total_duration) * 100))
                    bar_val = p_start + int((pct / 100.0) * (p_end - p_start))
                    emit(bar_val, f"Đang nhận diện phụ đề ({mode_label}): {pct}% ({format_srt_time(current_time)} / {format_srt_time(total_duration)})...")

                return collected, detected_lang, total_duration

            def _fill_missing_gaps_by_slicing(model, current_segs: list, target_lang: str, total_dur: float) -> list:
                gaps = find_uncovered_time_gaps(current_segs, total_dur, min_gap_sec=10.0)
                if not gaps:
                    return current_segs

                recovered = list(current_segs)
                chunk_len = 25.0

                for g_start, g_end in gaps:
                    cur_pos = max(0.0, g_start - 0.3)
                    while cur_pos < g_end - 2.0:
                        win_dur = min(chunk_len, g_end - cur_pos + 0.3)
                        if win_dur < 2.5:
                            break
                        emit(
                            82,
                            f"Đang quét bổ sung đoạn nhạc ({format_srt_time(cur_pos)} -> {format_srt_time(cur_pos + win_dur)})..."
                        )
                        slice_file = extract_audio_slice(audio_source, cur_pos, win_dur, ffmpeg_dir=ffmpeg_dir)
                        if slice_file:
                            try:
                                sub_segs, _, _ = _transcribe_pass(
                                    model,
                                    target_audio=slice_file,
                                    target_lang=target_lang,
                                    use_vad=False,
                                    time_offset=cur_pos,
                                    progress_range=(80, 88)
                                )
                                recovered.extend(sub_segs)
                            except Exception:
                                pass
                            finally:
                                if os.path.exists(slice_file):
                                    try:
                                        os.remove(slice_file)
                                    except Exception:
                                        pass
                        cur_pos += chunk_len - 1.0

                return recovered

            def _run_pipeline_on_device(target_device: str, target_compute: str) -> list:
                emit(15, f"Đang nạp mô hình ({actual_whisper_model}, {target_device.upper()} - {target_compute})...")
                model = _load_whisper_model(actual_whisper_model, target_device, target_compute)

                target_lang = lang_code
                if target_lang is None:
                    emit(20, "Đang quét thử 30s đầu để xác thực ngôn ngữ gốc (Việt / Anh)...")
                    target_lang, _ = verify_language_two_pass(
                        model=model,
                        audio_path=audio_source,
                        ffmpeg_dir=ffmpeg_dir,
                        user_lang=language,
                        platform_lang=platform_detected_lang
                    )
                    emit(24, f"Đã xác nhận ngôn ngữ gốc [{target_lang.upper()}]. Đang giải mã bám sát từng âm tiết...")

                segs_vad, detected_lang, total_dur = _transcribe_pass(
                    model,
                    target_audio=audio_source,
                    target_lang=target_lang,
                    use_vad=True,
                    time_offset=0.0,
                    progress_range=(25, 76)
                )

                fallback_lang = target_lang if target_lang else (detected_lang if detected_lang in ('vi', 'en') else 'vi')
                full_segs = _fill_missing_gaps_by_slicing(model, segs_vad, fallback_lang, total_dur)

                return fix_enjambment_and_sentence_boundaries(full_segs)

            if _is_cuda_available_and_loadable(ffmpeg_dir):
                try:
                    cleaned_ai_segments = _run_pipeline_on_device("cuda", "float16")
                except Exception:
                    emit(16, "Chuyển sang chế độ giải mã CPU...")
                    cleaned_ai_segments = _run_pipeline_on_device("cpu", "int8")
            else:
                cleaned_ai_segments = _run_pipeline_on_device("cpu", "int8")

        else:
            emit(15, f"Đang tải mô hình OpenAI whisper ({actual_whisper_model})...")
            import whisper
            model = whisper.load_model(actual_whisper_model)
            emit(35, "Đang phân tích âm thanh và tạo phụ đề...")
            result = model.transcribe(
                audio_source,
                language=lang_code if lang_code else "vi",
                initial_prompt=vocab_hint,
                word_timestamps=True,
                condition_on_previous_text=False,
                no_speech_threshold=None,
                compression_ratio_threshold=None,
                logprob_threshold=None,
                temperature=(0.0, 0.2, 0.4)
            )
            raw_fallback = []
            for seg in result.get("segments", []):
                raw_fallback.append({
                    'start': seg.get('start', 0),
                    'end': seg.get('end', 0),
                    'text': seg.get('text', ''),
                    'words': seg.get('words', []),
                    'no_speech_prob': seg.get('no_speech_prob', 0.0),
                    'avg_logprob': seg.get('avg_logprob', -0.4),
                    'compression_ratio': seg.get('compression_ratio', 1.0)
                })
            cleaned_ai_segments = fix_enjambment_and_sentence_boundaries(raw_fallback)

        if platform_auto_segments:
            emit(91, "Đang hợp nhất từ vựng theo mốc thời gian âm thanh thực...")
            fused_segments = reconcile_and_fuse_subtitles(cleaned_ai_segments, platform_auto_segments)
        else:
            fused_segments = cleaned_ai_segments

        emit(95, "Đang khôi phục nửa câu bị khuyết & đồng thuận điệp khúc toàn bài...")
        final_segments = ai_semantic_global_review(
            fused_segments,
            reference_lines=reference_lyric_lines,
            progress_callback=emit
        )

        emit(98, f"Đang ghi file phụ đề chuẩn thời gian thực: {os.path.basename(srt_path)}...")
        write_srt_file(final_segments, srt_path)

        emit(100, "Tạo phụ đề hoàn tất!")
        return srt_path

    finally:
        if temp_wav and temp_wav != video_path and os.path.exists(temp_wav) and (
            temp_wav.endswith("_temp_processed.wav") or temp_wav.endswith("_temp_vocal_for_srt.wav")
        ):
            try:
                os.remove(temp_wav)
            except Exception:
                pass