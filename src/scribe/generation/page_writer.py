"""Per-page generation: one LLM call per document instead of one call for the whole suite.

Generating every page of a doc plan in a single completion means N pages share ONE output
token budget -- for any real N (an 8-page suite, let alone a 20-page one), that caps each
page's depth far below what the model could produce writing one document at a time. This
module generates each `DocPage` with its own call (and its own `--max-tokens` budget), with
transparent fallbacks for when a single page's own budget still isn't enough (observed in
practice against a real local model): a continuation call first, then one fresh retry at a
doubled token budget, then an explicit request for a deliberately condensed version as a last
resort -- and if a single page still can't be produced, a clearly marked placeholder is written
for THAT page only instead of failing the entire run.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from scribe.constants import DOC_END_MARKER
from scribe.generation import qa, writer
from scribe.generation.doc_plan import DocPage
from scribe.generation.prompt_builder import build_repair_followup
from scribe.generation.tokens import estimate_token_count
from scribe.providers.llm_client import LLMClient

StatusCallback = Callable[[str], None]

_DEFAULT_MAX_TOKENS = 8192  # mirrors OpenAIClient's own fallback default (providers/llm_client.py)
_TRUNCATION_TOKEN_RATIO = 0.95  # a response this close to its own cap is almost certainly cut off
_MAX_CONTINUATION_ATTEMPTS = 2
_MAX_TOKEN_ESCALATIONS = 1
_TOKEN_ESCALATION_CEILING = 32_000


class GenerationFailedError(RuntimeError):
    """Raised when a single page's output still fails validation after all repair attempts."""


_MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\(([^)#]+)\)")


def _neutralize_dead_links(body: str, dead_targets: set[str]) -> str:
    """Strip just the broken cross-links (keep the visible text) rather than discarding an
    otherwise-good page over one or two bad references -- e.g. a link to a real file that
    exists in the repo (seen in the Project Context tree) but isn't part of this doc suite."""

    def _replace(match: re.Match[str]) -> str:
        text, target = match.group(1), match.group(2)
        target_name = target.split("/")[-1].lstrip("./")
        return text if target_name in dead_targets else match.group(0)

    return _MARKDOWN_LINK_PATTERN.sub(_replace, body)


def looks_truncated(response: str, doc_id: str, max_tokens: int) -> bool:
    """Best-effort truncation detector for one page's raw completion.

    Primary signal: the response contains this doc's opening marker but never closes it --
    for a single-page call there's no legitimate reason the model would do that on purpose, so
    this is treated as truncation regardless of token count. Secondary signal (covering the
    case where even the opening marker itself got cut off): the response consumed almost the
    entire requested token budget, which a naturally-finished reply rarely does by coincidence.
    """
    has_begin = f'doc="{doc_id}"' in response
    has_end = DOC_END_MARKER in response
    if has_begin and not has_end:
        return True
    if not has_begin and not has_end:
        return estimate_token_count(response) >= max_tokens * _TRUNCATION_TOKEN_RATIO
    return False


def _continue_page(
    client: LLMClient,
    model: str,
    doc_id: str,
    partial_response: str,
    *,
    temperature: float | None,
    max_tokens: int,
    on_status: StatusCallback,
) -> str:
    """Ask the model to continue a truncated page from exactly where it stopped."""
    continuation_prompt = (
        f'Your previous response for the document with doc id "{doc_id}" was cut off before '
        "finishing. Continue writing the SAME document from exactly where it left off -- do not "
        "repeat earlier content, do not restart, and do not re-emit the opening "
        f'`<!-- SCRIBE:BEGIN doc="{doc_id}" -->` marker. When the document is complete, close it '
        f"by writing `{DOC_END_MARKER}` on its own line.\n\n"
        f"--- YOUR PREVIOUS (CUT OFF) RESPONSE ---\n{partial_response}"
    )
    continuation = client.complete(continuation_prompt, model, temperature=temperature, max_tokens=max_tokens)
    on_status(f"Continued '{doc_id}' after an apparent output-length cutoff.")
    return partial_response.rstrip() + "\n" + continuation


def _resolve_truncation(
    client: LLMClient,
    model: str,
    prompt: str,
    doc_id: str,
    response: str,
    *,
    temperature: float | None,
    max_tokens: int,
    on_status: StatusCallback,
) -> str:
    """Return a (hopefully) untruncated response for `doc_id`, escalating through fallbacks.

    Order: continuation call(s) at the same budget -> one fresh retry at a doubled budget (with
    its own continuation attempts) -> a final explicit request for a condensed version. Each
    stage runs only if the previous one still looks truncated.
    """
    current_max_tokens = max_tokens
    continuations = 0
    while (
        looks_truncated(response, doc_id, current_max_tokens) and continuations < _MAX_CONTINUATION_ATTEMPTS
    ):
        continuations += 1
        on_status(
            f"'{doc_id}' looks truncated near the {current_max_tokens}-token output cap; "
            f"requesting continuation {continuations}/{_MAX_CONTINUATION_ATTEMPTS}."
        )
        response = _continue_page(
            client,
            model,
            doc_id,
            response,
            temperature=temperature,
            max_tokens=current_max_tokens,
            on_status=on_status,
        )

    if looks_truncated(response, doc_id, current_max_tokens):
        current_max_tokens = min(current_max_tokens * 2, _TOKEN_ESCALATION_CEILING)
        on_status(f"Still truncated; retrying '{doc_id}' with a higher cap ({current_max_tokens} tok).")
        response = client.complete(prompt, model, temperature=temperature, max_tokens=current_max_tokens)
        continuations = 0
        while (
            looks_truncated(response, doc_id, current_max_tokens)
            and continuations < _MAX_CONTINUATION_ATTEMPTS
        ):
            continuations += 1
            response = _continue_page(
                client,
                model,
                doc_id,
                response,
                temperature=temperature,
                max_tokens=current_max_tokens,
                on_status=on_status,
            )

    if looks_truncated(response, doc_id, current_max_tokens):
        on_status(f"Still hitting the output limit for '{doc_id}'; asking for a condensed version instead.")
        condensed_prompt = (
            f"{prompt}\n\n---INSTRUCTIONS---\nOutput length constraints were hit repeatedly for "
            "this document. Write a noticeably MORE CONCISE version this time -- cover only the "
            "essential facts, skip elaboration -- while still meeting the format requirements above."
        )
        response = client.complete(
            condensed_prompt, model, temperature=temperature, max_tokens=current_max_tokens
        )

    return response


def generate_with_repair(
    client: LLMClient,
    prompt: str,
    model: str,
    expected_doc_ids: list[str],
    max_repair_attempts: int,
    on_status: StatusCallback,
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    known_doc_ids: set[str] | None = None,
) -> dict[str, str]:
    """Call the LLM, validating (structure + QA) and re-prompting on failure.

    Returns `{doc_id: body}` once both the marker-structure validation and the QA pass (mermaid
    validity, dead links, placeholders) pass. Raises `GenerationFailedError` if issues remain
    after `max_repair_attempts` follow-up rounds. When `expected_doc_ids` has exactly one entry
    (the per-page generation path), each raw completion also goes through truncation-recovery
    (`_resolve_truncation`) before validation, transparent to the repair loop here.

    `known_doc_ids` is the full doc plan's ids, used for QA's cross-link check -- NOT just
    `expected_doc_ids` -- so a per-page call (which only ever sees the one page it's generating)
    doesn't flag every legitimate cross-link to a sibling page as a dead link. Defaults to
    `expected_doc_ids` for whole-suite-style calls where that's already the full set.
    """
    resolved_max_tokens = max_tokens or _DEFAULT_MAX_TOKENS
    conversation_prompt = prompt
    last_issue_description = "unknown error"
    single_page_id = expected_doc_ids[0] if len(expected_doc_ids) == 1 else None
    resolved_known_doc_ids = known_doc_ids if known_doc_ids is not None else set(expected_doc_ids)
    last_found: dict[str, str] | None = None
    last_dead_link_only_issues: list[qa.QAIssue] | None = None

    for attempt in range(max_repair_attempts + 1):
        response = client.complete(
            conversation_prompt, model, temperature=temperature, max_tokens=resolved_max_tokens
        )
        if single_page_id is not None:
            response = _resolve_truncation(
                client,
                model,
                conversation_prompt,
                single_page_id,
                response,
                temperature=temperature,
                max_tokens=resolved_max_tokens,
                on_status=on_status,
            )
        validation = writer.validate_sections(response, expected_doc_ids)

        if not validation.ok:
            last_issue_description = validation.describe()
            last_dead_link_only_issues = None
            on_status(f"Validation failed (attempt {attempt + 1}): {last_issue_description}")
        else:
            qa_report = qa.review_documents(validation.found, known_doc_ids=resolved_known_doc_ids)
            if qa_report.ok:
                return validation.found
            last_issue_description = qa_report.describe()
            last_found = validation.found
            non_dead_link = [issue for issue in qa_report.issues if issue.category != "dead_link"]
            last_dead_link_only_issues = qa_report.issues if not non_dead_link else None
            on_status(f"QA issues found (attempt {attempt + 1}): {last_issue_description}")

        if attempt == max_repair_attempts:
            break

        followup = build_repair_followup(last_issue_description)
        conversation_prompt = (
            f"{prompt}\n\n---PREVIOUS RESPONSE (INVALID)---\n{response}\n\n---INSTRUCTIONS---\n{followup}"
        )

    if last_dead_link_only_issues and last_found is not None:
        dead_targets = {issue.target for issue in last_dead_link_only_issues if issue.target}
        on_status(
            f"Auto-healing {len(dead_targets)} dead link(s) instead of discarding this page: "
            f"{', '.join(sorted(dead_targets))}."
        )
        return {doc_id: _neutralize_dead_links(body, dead_targets) for doc_id, body in last_found.items()}

    raise GenerationFailedError(
        f"LLM output still invalid after {max_repair_attempts} repair attempt(s): {last_issue_description}"
    )


def _stub_body(page: DocPage, error: Exception) -> str:
    return (
        f"# {page.title}\n\n"
        "> **Generation failed for this page.** S.C.R.I.B.E. could not produce valid content "
        f"for `{page.id}` after all repair and output-length fallbacks. Last error: {error}\n\n"
        "Retry this page specifically with `--refresh-plan`, a higher `--max-tokens`, or a "
        "different `--model`/`--provider`; this placeholder was written so the rest of the "
        "suite could still be generated."
    )


def generate_pages(
    client: LLMClient,
    model: str,
    pages: list[DocPage],
    build_prompt_for_page: Callable[[DocPage], str],
    max_repair_attempts: int,
    on_status: StatusCallback,
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    all_doc_ids: list[str] | None = None,
) -> tuple[dict[str, str], list[str]]:
    """Generate every page with its own LLM call (and its own repair/truncation handling).

    `all_doc_ids` is the full doc plan (defaults to just `pages`' own ids if not given) --
    passed to QA's dead-link check so cross-links to sibling pages not in `pages` aren't
    incorrectly flagged, e.g. when generating a subset of a larger suite.

    Returns `({doc_id: body}, failed_page_ids)`. A page that still can't be produced after every
    fallback gets a clearly marked placeholder body instead of aborting the whole run.
    """
    known_doc_ids = set(all_doc_ids) if all_doc_ids is not None else {page.id for page in pages}
    documents: dict[str, str] = {}
    failed_page_ids: list[str] = []
    for page in pages:
        prompt = build_prompt_for_page(page)
        try:
            result = generate_with_repair(
                client,
                prompt,
                model,
                [page.id],
                max_repair_attempts,
                on_status,
                temperature=temperature,
                max_tokens=max_tokens,
                known_doc_ids=known_doc_ids,
            )
            documents.update(result)
            on_status(f"Generated '{page.id}'.")
        except GenerationFailedError as exc:
            on_status(f"Giving up on '{page.id}' after all fallbacks ({exc}); writing a placeholder instead.")
            documents[page.id] = _stub_body(page, exc)
            failed_page_ids.append(page.id)
    return documents, failed_page_ids
