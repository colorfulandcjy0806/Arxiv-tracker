# -*- coding: utf-8 -*-
import os, re, sys, traceback, time, pathlib, click
from .config import Settings
from .query import build_search_query
from .client import fetch_arxiv_feed
from .parser import parse_feed
from .output import save_json, save_markdown
from .summarizer import build_two_stage_summary
from .llm import call_llm_translate
from .email_template import render_email_html
from .exporter import md_to_pdf

# 进程级防重：本进程内只允许发送一次
_SENT_EMAIL = False


def _split_categories(values):
    out = []
    for v in values or []:
        if not v:
            continue
        parts = re.split(r'\s*,\s*|\s*;\s*|/', v.strip())
        out.extend([p for p in parts if p])
    return out


def _split_keywords(values):
    out = []
    for v in values or []:
        if not v:
            continue
        parts = re.split(r'\s*,\s*|\s*;\s*', v.strip())
        out.extend([p for p in parts if p])
    return out


def _load_raw_cfg(maybe_path):
    import yaml
    path = maybe_path or "config.yaml"
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _extract_stamp_from_path(path: str) -> str:
    """从 outputs/arxiv_YYYYMMDD_HHMMSS.json 推断快照 stamp；兜底为当天日期"""
    try:
        name = os.path.basename(path or "")
        m = re.search(r"arxiv_(\d{8}_\d{6})", name)
        if m:
            return m.group(1)
    except Exception:
        pass
    return time.strftime("%Y%m%d")


def _norm_addr(s: str) -> str:
    return re.sub(r"\s+", "", (s or "")).lower()


def _dedup_addrs(seq):
    seen = set()
    out = []
    for x in seq or []:
        k = _norm_addr(x)
        if k and k not in seen:
            out.append(k)
            seen.add(k)
    return out


@click.group()
def cli():
    """arxiv-tracker CLI"""
    pass


@cli.command("run")
@click.option("--config", "config_path", type=click.Path(exists=True), help="配置文件路径（YAML）")
@click.option("--categories", multiple=True, help="学科分类，可多次或逗号分隔")
@click.option("--keywords", multiple=True, help="关键词，可多次或逗号分隔")
@click.option("--exclude-keywords", multiple=True, help="排除关键词，可多次或逗号分隔") 
@click.option("--logic", type=click.Choice(["AND", "OR"], case_sensitive=False), default=None)
@click.option("--max-results", type=int, default=None)
@click.option("--sort-by", type=click.Choice(["submittedDate", "lastUpdatedDate"]), default=None)
@click.option("--sort-order", type=click.Choice(["ascending", "descending"]), default=None)
@click.option("--lang", type=click.Choice(["zh", "en", "both"]), default=None, help="输出语言")
@click.option("--summary-mode", type=click.Choice(["none", "heuristic", "llm"]), default=None)
@click.option("--summary-scope", type=click.Choice(["tldr", "full", "both"]), default=None)
@click.option("--email", "email_enabled", is_flag=True, default=None, help="启用邮件发送（覆盖配置）")
@click.option("--email-detail", type=click.Choice(["simple", "full"]), default=None, help="邮件内容详略")
@click.option("--email-max-items", type=int, default=None, help="邮件最多包含的条目数")
@click.option("--out-dir", default="outputs", help="输出目录")
@click.option("--verbose", is_flag=True, help="打印详细运行日志")
@click.option("--translate", "translate_enabled", is_flag=True, default=None, help="启用 LLM 中文翻译（覆盖配置）")
@click.option("--translate-lang", type=click.Choice(["zh"]), default=None, help="翻译目标语言")
@click.option("--pdf", "pdf_enabled", is_flag=True, default=False, help="将 Markdown 同步导出为 PDF")
@click.option("--site-dir", default=None, help="输出静态站点目录（如 docs）")
@click.option("--site-url", default=None, help="站点首页 URL（用于邮件正文链接）")
@click.option("--no-email", is_flag=True, help="跳过邮件发送（用于重试）")

def run(config_path, categories, keywords, exclude_keywords, logic, max_results, sort_by, sort_order,
        lang, summary_mode, summary_scope, email_enabled, email_detail, email_max_items,
        out_dir, verbose, translate_enabled, translate_lang, pdf_enabled, no_email: bool,
        site_dir, site_url):
    try:
        if verbose:
            click.echo("[Run] Start")

        # 1) 载入设置
        cfg = Settings.from_file(config_path) if config_path else Settings()
        cats = _split_categories(categories)
        keys = _split_keywords(keywords)
        ex_keys = _split_keywords(exclude_keywords)
        cfg.merge_cli(categories=cats or None,
                      keywords=keys or None,
                      exclude_keywords=ex_keys or None,
                      logic=(logic or cfg.logic),
                      max_results=(max_results or cfg.max_results),
                      sort_by=(sort_by or cfg.sort_by),
                      sort_order=(sort_order or cfg.sort_order))

        raw_cfg = _load_raw_cfg(config_path)
        lang = lang or raw_cfg.get("lang", "both")

        # 摘要
        summary_cfg = raw_cfg.get("summary", {}) or {}
        llm_cfg = raw_cfg.get("llm", {}) or {}
        mode = summary_mode or summary_cfg.get("mode", "none")
        scope = summary_scope or summary_cfg.get("scope", "both")

        # 翻译
        trans_cfg = (raw_cfg.get("translate", {}) or {}).copy()
        if translate_enabled is not None:
            trans_cfg["enabled"] = translate_enabled
        if translate_lang:
            trans_cfg["lang"] = translate_lang
        if "fields" not in trans_cfg:
            trans_cfg["fields"] = ["title", "summary"]

        # —— 邮件配置（合并 config + CLI 覆盖 + no-email）——
        email_cfg = (raw_cfg.get("email", {}) or {}).copy()
        if email_enabled is not None:
            email_cfg["enabled"] = bool(email_enabled)
        if email_detail:
            email_cfg["detail"] = email_detail
        if email_max_items is not None:
            email_cfg["max_items"] = int(email_max_items)
        # no-email 优先级最高
        if no_email:
            email_cfg["enabled"] = False
        # 兜底默认值
        email_cfg.setdefault("enabled", False)
        email_cfg.setdefault("detail", "full")
        email_cfg.setdefault("max_items", 50)

        # —— Freshness & 去重配置 —— #
        fresh_cfg = (raw_cfg.get("freshness") or {})
        since_days = int(fresh_cfg.get("since_days", 0) or 0)          # 近 N 天（0=不启用）
        unique_only = bool(fresh_cfg.get("unique_only", False))        # 跨天去重
        state_path = fresh_cfg.get("state_path", ".state/seen.json")   # 去重状态文件
        fallback_when_empty = bool(fresh_cfg.get("fallback_when_empty", False))
        if verbose:
            click.echo("[Freshness] since_days={}, unique_only={}, state_path='{}', fallback_when_empty={}"
                       .format(since_days, unique_only, state_path, fallback_when_empty))

        if verbose:
            click.echo("[Run] categories: {}".format(cfg.categories))
            click.echo("[Run] keywords  : {}".format(cfg.keywords))
            click.echo("[Run] summary   : {}/{}".format(mode, scope))
            click.echo("[Run] lang      : {}".format(lang))
            click.echo("[Run] translate : {} -> {}".format(trans_cfg.get("enabled", False),
                                                          trans_cfg.get("lang", "zh")))
            click.echo("[Run] email     : enabled={}, detail={}, max_items={}".format(
                email_cfg.get("enabled", False), email_cfg.get("detail"), email_cfg.get("max_items")
            ))

        # 2) 查询（分页抓取直到攒够“未读新条目”或触达时间窗）
        from datetime import datetime, timedelta, timezone
        import json, pathlib

        def _parse_dt(s: str):
            if not s:
                return None
            s = s.replace("Z", "+00:00")
            try:
                return datetime.fromisoformat(s).astimezone(timezone.utc)
            except Exception:
                return None
        q = build_search_query(cfg.categories, cfg.keywords, cfg.exclude_keywords, cfg.logic)
        click.echo("[Query] {}".format(q))

        # 读取已见集合（兼容 list / {"ids":[...]} / {id: timestamp} 三种格式）
        seen_ids = set()
        if unique_only and state_path:
            try:
                if os.path.exists(state_path):
                    with open(state_path, "r", encoding="utf-8") as f:
                        j = json.load(f) or {}
                        if isinstance(j, dict) and "ids" in j:
                            seen_ids = set(j.get("ids") or [])
                        elif isinstance(j, dict):
                            seen_ids = set(j.keys())
                        elif isinstance(j, list):
                            seen_ids = set(j)
            except Exception:
                seen_ids = set()

        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days) if since_days > 0 else None
        want_new = int(cfg.max_results or 50)

        # 分页参数（可按需改成配置）
        page_size = min(200, max(25, want_new))  # 25~200 较稳
        max_pages = 20
        start = 0
        collected, reached_cutoff = [], False

        for _page in range(max_pages):
            xml = fetch_arxiv_feed(
                q, start=start, max_results=page_size,
                sort_by=cfg.sort_by, sort_order=cfg.sort_order
            )
            page_items = parse_feed(xml) or []
            if not page_items:
                break

            for it in page_items:
                # 时间窗（按 updated 优先；无则退回 published）
                t = _parse_dt(it.get("updated")) or _parse_dt(it.get("published"))
                if cutoff and t and t < cutoff:
                    reached_cutoff = True
                    break

                # 去重
                aid = it.get("id")
                if unique_only and aid and aid in seen_ids:
                    continue

                collected.append(it)
                if len(collected) >= want_new:
                    break

            if len(collected) >= want_new or reached_cutoff:
                break

            if len(page_items) < page_size:
                # 已无更多可翻页内容
                break

            start += page_size

        # Fallback：若空且允许回退，则给最新一页（不考虑去重/时间窗）
        if not collected and fallback_when_empty:
            xml = fetch_arxiv_feed(
                q, start=0, max_results=want_new,
                sort_by=cfg.sort_by, sort_order=cfg.sort_order
            )
            collected = parse_feed(xml) or []

        items = collected
        if not items:
            click.secho("[Info] No new items after pagination/freshness/dedup filter.", fg="yellow")
        else:
            click.echo(f"[Info] Fetched {len(items)} new item(s) after pagination/dedup.")

        # 先从已有文本/HTML提取；若仍没有再扫 PDF 头部兜底
        scrape_cfg = (raw_cfg.get("scrape") or {})
        scrape_html = bool(scrape_cfg.get("html", True))
        scrape_pdf_if_missing = bool(scrape_cfg.get("pdf_if_missing", True))
        scrape_pdf_always = bool(scrape_cfg.get("pdf_first_page", False))
        scrape_to = int(scrape_cfg.get("timeout", 10))

        from .extrascrape import augment_item_links

        if verbose:
            click.echo(f"[Scrape] html={scrape_html} pdf_if_missing={scrape_pdf_if_missing} "
                       f"pdf_first_page={scrape_pdf_always} timeout={scrape_to}")

        for it in items:
            try:
                added = augment_item_links(
                    it,
                    html=scrape_html,
                    pdf_if_missing=scrape_pdf_if_missing,
                    pdf_first_page=scrape_pdf_always,
                    timeout=scrape_to,
                )
                if verbose and added > 0:
                    click.echo(f"[Scrape] +{added} code link(s) for {(it.get('id') or '')[:32]}")
            except Exception as e:
                click.secho(f"[Scrape] 补链失败 {(it.get('id') or '')[:18]}...: {e}", fg="yellow")

        # 3) 摘要
        summaries_zh, summaries_en = {}, {}
        def _sum_for_lang(L):
            out = {}
            for it in items:
                sid = it.get("id") or ""
                out[sid] = build_two_stage_summary(item=it, mode=mode, lang=L, scope=scope, llm_cfg=llm_cfg)
            return out

        if lang in ("zh", "both"):
            summaries_zh = _sum_for_lang("zh")
        if lang in ("en", "both"):
            summaries_en = _sum_for_lang("en")

        # 4) 翻译（中文）
        translations = {}
        if trans_cfg.get("enabled") and (trans_cfg.get("lang", "zh") == "zh"):
            api_key = (llm_cfg.get("api_key")
                       or os.getenv(llm_cfg.get("api_key_env") or "OPENAI_API_KEY", ""))
            if not api_key:
                click.secho("[Translate] 跳过：未找到 LLM API Key（配置 llm.api_key 或设置环境变量 {}）"
                            .format(llm_cfg.get("api_key_env") or "OPENAI_API_KEY"), fg="yellow")
            else:
                for it in items:
                    sid = it.get("id") or ""
                    try:
                        translations[sid] = call_llm_translate(
                            item=it, target_lang="zh",
                            base_url=llm_cfg.get("base_url", ""),
                            model=llm_cfg.get("model", ""),
                            api_key=api_key,
                            system_prompt=llm_cfg.get("system_prompt_translate_zh", "")
                        )
                    except Exception as e:
                        click.secho(f"[Translate] 失败 {sid[:18]}...: {e}", fg="red")

        # 5) 终端预览
        if not items:
            click.echo("（今日暂无新增）")
        for idx, it in enumerate(items, 1):
            title = it.get("title", "")
            venue = it.get("venue_inferred") or (it.get("journal_ref") or "")
            click.echo(f"{idx:02d}. {title}  [{' / '.join(it.get('authors', []))}]")
            if venue:
                click.echo(f"    Venue: {venue}")
            click.echo(f"    Time: {it.get('published', '—')}  ->  {it.get('updated', '—')}")
            if it.get("pdf_url"):
                click.echo(f"    PDF : {it['pdf_url']}")
            sid = it.get("id") or ""
            s = (summaries_zh.get(sid) or summaries_en.get(sid) or {})
            if s.get("tldr"):
                click.echo(f"    TL;DR: {s['tldr']}")
            tx = translations.get(sid)
            if tx and tx.get("title_zh"):
                click.echo(f"    标题(中): {tx['title_zh']}")
            click.echo("")

        # 6) 保存到文件 + 生成 PDF（可选）
        json_path = save_json(items, out_dir)
        md_path   = save_markdown(items, out_dir, summaries_zh, summaries_en, lang=lang, translations=translations)
        click.echo(f"Saved: {json_path}")
        click.echo(f"Saved: {md_path}")

        # 6.5) 生成站点（如启用）
        page_url = None
        site_generated = False
        try:
            from .sitegen import generate_site
            site_cfg = (raw_cfg.get("site") or {}) if 'raw_cfg' in locals() else {}
            sd = site_dir or site_cfg.get("dir")
            if sd and (site_cfg.get("enabled", False) or site_dir is not None):
                keep = int(site_cfg.get("keep_runs", 60))
                title = site_cfg.get("title", "arXiv Results")
                theme = site_cfg.get("theme", "light")
                accent = site_cfg.get("accent", "#2563eb")
                site_res = generate_site(
                    items=items,
                    summaries_zh=summaries_zh or {},
                    summaries_en=summaries_en or {},
                    translations=translations or {},
                    site_dir=sd, site_title=title, keep_runs=keep,
                    theme=theme, accent=accent
                )
                click.echo(f"Saved: {site_res['index_path']}")
                page_url = site_url or site_cfg.get("url")
                if page_url and not page_url.endswith("/"):
                    page_url += "/"
                site_generated = True
        except Exception as e:
            click.secho(f"[Site] 生成失败: {e}", fg="red")

        pdf_path = ""
        if pdf_enabled:
            try:
                pdf_path = md_to_pdf(md_path)
                click.echo(f"Saved: {pdf_path}")
            except Exception as e:
                click.secho(f"[PDF] 生成失败: {e}", fg="red")

        # 7) 邮件发送（富模板 + 附件 [md] + 顶部“Web 版”）
        email_sent = False
        if email_cfg.get("enabled"):
            try:
                # 进程级防重（本进程只发一次）
                global _SENT_EMAIL
                if _SENT_EMAIL:
                    click.secho("[Email] 已在本进程发送过，跳过（process guard）", fg="yellow")
                    email_cfg["enabled"] = False

                # 快照级防重（同一个快照只发一次）
                def _fallback_stamp(p: str) -> str:
                    b = os.path.basename(p or "")
                    return os.path.splitext(b)[0]
                try:
                    stamp = _extract_stamp_from_path(json_path)
                except Exception:
                    stamp = _fallback_stamp(json_path)

                flag_dir = pathlib.Path(out_dir or "outputs")
                flag_dir.mkdir(parents=True, exist_ok=True)
                flag_path = flag_dir / f"email_sent_{stamp}.flag"
                if email_cfg.get("enabled") and flag_path.exists():
                    click.secho(f"[Email] 本次快照({stamp})已发送过，跳过（file guard）", fg="yellow")
                    email_cfg["enabled"] = False

                if email_cfg.get("enabled"):
                    # 环境变量优先（适合 GitHub Actions）
                    env_to = os.getenv("EMAIL_TO", "")
                    to_list = [x.strip() for x in re.split(r"[;,]", env_to) if x.strip()] if env_to else (email_cfg.get("to") or [])
                    sender_env = os.getenv("EMAIL_SENDER", "")
                    sender = sender_env or (email_cfg.get("sender") or "")
                    server  = email_cfg.get("smtp_server") or "smtp.qq.com"
                    port    = int(email_cfg.get("smtp_port") or 465)
                    user_env= os.getenv("SMTP_USER", "")
                    user    = user_env or (email_cfg.get("smtp_user") or sender)
                    pass_env= email_cfg.get("smtp_pass_env") or "SMTP_PASS"
                    passwd  = os.getenv(pass_env, "")
                    subject = email_cfg.get("subject") or "[arXiv] Digest"
                    tls_mode= email_cfg.get("tls", "auto")
                    debug   = bool(email_cfg.get("debug", False))
                    detail  = email_cfg.get("detail", "full")
                    max_items = int(email_cfg.get("max_items", 50))

                    # 收件人去重
                    try:
                        _ = _dedup_addrs
                    except NameError:
                        def _dedup_addrs(lst):
                            s, out = set(), []
                            for a in lst or []:
                                a2 = a.lower()
                                if a2 not in s:
                                    s.add(a2); out.append(a)
                            return out
                    to_list = _dedup_addrs(to_list)

                    if not (to_list and sender and passwd):
                        click.secho("[Email] 配置不完整，跳过发送（需要 EMAIL_TO / EMAIL_SENDER / SMTP_PASS）", fg="yellow")
                    else:
                        html_body = ""
                        if page_url:
                            html_body += f'<div style="margin-bottom:10px">Web 版：<a href="{page_url}">{page_url}</a></div>'
                        if not items:
                            html_body += "<p>今日暂无新增命中。</p>"
                        else:
                            html_body += render_email_html(
                                items=items, lang=lang, translations=translations,
                                summaries_zh=summaries_zh, summaries_en=summaries_en,
                                detail=detail, max_items=max_items,
                                title=subject.replace("[arXiv]", "arXiv")
                            )
                        from .mailer import send_email
                        attach = []
                        if email_cfg.get("attach_md", False) and md_path:
                            attach.append(md_path)

                        click.echo(f"[Email] will send: detail={detail} to={len(to_list)} recipient(s)")
                        send_email(
                            sender=sender, to_list=to_list, subject=subject, html_body=html_body,
                            smtp_server=server, smtp_port=port, smtp_user=user, smtp_pass=passwd,
                            tls_mode=tls_mode, attachments=attach, debug=debug, timeout=20
                        )
                        _SENT_EMAIL = True
                        email_sent = True
                        try:
                            flag_path.touch()
                        except Exception:
                            pass
                        click.echo("[Email] 已发送")
            except Exception as e:
                click.secho("[Email] 发送失败: {}".format(e), fg="red")

        # 8) —— 仅在“网页生成成功或邮件成功发送”后，才持久化去重状态 —— #
        try:
            if unique_only and state_path and items and (site_generated or email_sent):
                all_seen = set(seen_ids)
                for it in items:
                    aid = it.get("id")
                    if aid:
                        all_seen.add(aid)
                p = pathlib.Path(state_path)
                p.parent.mkdir(parents=True, exist_ok=True)
                with open(p, "w", encoding="utf-8") as f:
                    json.dump({"ids": sorted(all_seen)}, f, ensure_ascii=False, indent=2)
                click.echo(f"[Freshness] 更新去重状态，共 {len(all_seen)} 条 -> {state_path}")
            elif unique_only and items:
                click.echo("[Freshness] 未写入去重状态（本次既未成功发邮件也未生成站点）")
        except Exception as e:
            click.secho(f"[Freshness] 保存去重状态失败: {e}", fg="yellow")

        if verbose:
            click.echo("[Run] Done")

    except Exception as e:
        click.secho("[Run] ERROR: {}".format(e), fg="red")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    cli()
