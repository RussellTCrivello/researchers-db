# Phase 6 — one setting that changes where data entry happens

The request, in the user's words: *"an option or a setting — perhaps a toggle — that serves an
important purpose: allowing all interfaces for adding, editing, and similar tasks to appear as
organized, well-structured pop-up windows, rather than as standard, full-page views … a
comprehensive, professional-grade setting."*

Three things that sentence rules out, and that shaped the design:

1. **Not an experiment bolted onto one entity.** Every create/edit surface in the product has to move
   together — otherwise the interface is inconsistent, which is worse than either choice alone.
2. **Not a stretched page.** A dialog that merely inherits page markup is a page with a shadow. The
   form inside the dialog has to be organised for the smaller frame: grouped sections, a fixed footer
   with the real actions, a body that scrolls on its own.
3. **Not a preference buried in `localStorage`.** An instance-wide default belongs in the database and
   in the API, so every browser and every operator sees the same thing, and a person may still
   override it for themselves.

Everything below was verified by running it (`pytest`, `verify_all`, `ui_smoke`, `ui_full`, `audit`);
the counts are at the end.

---

## 1 · The setting

One control, in **Settings → Data-entry surface** (`#/settings`), with three cards that preview what
they do, a scope switch, a width selector and a **"Open a form"** button that opens a real dialog
immediately so the choice can be tried before it is trusted.

| Mode | What happens |
|---|---|
| **Full page** | `#/entity/person/new` renders the form as its own page, as in phases 1–5. |
| **Pop-up window** | The same form opens as a dialog over the list (new) or over the dossier (edit). |
| **Automatic** | Dialog on viewports ≥ 960 px, page below that — the choice most people will leave selected. |

Two levels, one answer:

* **Instance default** — stored in the `setting` table (`ui.form_mode`, `ui.form_dialog_size`) and
  served by `/api/meta`, so the very first paint already knows it (no flash of the wrong surface).
  Changed through `PUT /api/settings`, i.e. it is auditable configuration, not browser state.
* **Personal override** — `localStorage` (`siraj.form_mode`, `siraj.form_dialog_size`). The scope
  switch says which one is in force and what the other one is set to, so there is never a mystery
  about why a form behaved a certain way.

Resolution order: personal override → instance default → `page`. `A.formModeSource()` returns
`{mode, source: "personal"|"instance"}`, which is what the settings screen prints.

Migration `007_ui_form_mode.sql` seeds `ui.form_mode = page` and `ui.form_dialog_size = xl`, so an
upgraded installation behaves exactly as it did before until somebody chooses otherwise.

Dialog width has three values (`default`, `wide`, `xl`); `default` means "whatever the instance
says". `xl` is the default because the person form is a nine-section document, not a login box.

---

## 2 · Which surfaces move — the whole inventory

`app/static/js/views/record.js` owns one form shell, and *both* surfaces render through it. There is no
second copy of the form to drift out of step.

| Surface | Route | Dialog | Page |
|---|---|---|---|
| New person/place/institution/relationship/source/event | `#/entity/{e}/new` | ✔ | ✔ |
| Edit any record | `#/entity/{e}/{id}/edit` | ✔ | ✔ |
| Inline "create a missing related record" from a field | modal | ✔ | ✔ (unchanged) |
| Duplicate review and merge | modal | ✔ | ✔ (unchanged) |
| Import wizard, bulk edit, settings, saved-view editor | — | — | deliberately a page |

The last row is a decision, not an omission: a four-step import with a staged preview, or a bulk edit
that rewrites hundreds of rows, is a *task* with its own progress and its own failure modes. Shrinking
it into a dialog would hide work rather than present it. Everything that is "a record, entered" is a
form and follows the setting.

`A.forms.open(entity, id, {returnTo})` is the single entry point; deep links
(`#/entity/person/12/edit`) obey the setting too, so a link opened in a message lands on the surface
the reader prefers.

---

## 3 · What "well organised" means inside the frame

The form is the same object in both surfaces — nine collapsible sections, the same field controls, the
same validation — but the frame gives it what a page did not need:

| Concern | Page | Dialog |
|---|---|---|
| Headings | page header + breadcrumbs | dialog title, subtitle = `CODE · v3`, breadcrumbs stay on the page behind |
| Actions | a bar appended to the form | a sticky footer (`modal.foot`), always visible while the body scrolls |
| Scrolling | the document scrolls | only the dialog body scrolls; the head and footer stay put |
| Context | the form *is* the screen | the list or dossier stays visible behind it, so a new record is entered *next to* its siblings |

Sizes: `slim` (confirmations), `wide`, `xl` (record forms by default), `full`. The body is a grid of
sections; `xl` is wide enough for the two-column field layout without touching the page behind.

Save / Save + New / Cancel live in the footer; the footer also carries the dirty indicator and the
"fields marked ✱ are computed" note, so the two facts a person needs while editing never scroll away.

---

## 4 · The behaviour contract

These are the parts that make a dialog trustworthy, and every one of them is asserted in
`tests/ui_full.py`:

* **Focus moves in** — to the first input, not to the Save button.
* **Focus stays in** — Tab and Shift+Tab cycle inside the dialog. With nested dialogs (a combobox
  "create new source" opened from inside a form) only the *topmost* dialog owns Escape and Tab
  (`modalStack`), so Escape closes the small one, not both.
* **Escape / × / backdrop ask before losing work** — `onRequestClose` runs the same
  "Discard changes?" guard; declining leaves the draft exactly as it was.
* **Focus goes back** — closing returns the cursor to the control that opened the dialog.
* **The address stays truthful** — the hash is swapped (`replaceState`), never pushed, so a reload
  shows the page behind and Back means "leave this page", not "reopen the dialog".
* **Save + New keeps the surface** — the record is created, the dialog closes and a fresh draft of the
  same shape opens over the same list.
* **Editing keeps the dossier visible** — you can see the record you are editing behind the dialog.
* **Navigation wins** — any route change closes a stray form dialog (`app.js render()`), so a dialog
  can never float over somebody else's page.
* **The page behind is not repainted** — views stamp `root.dataset.surface`
  (`list:{entity}`, `record:{entity}:{id}`); the dialog only renders a page behind it when that page is
  not already there. A list of 25 live rows stays exactly as it was.
* **The skeleton is skipped** — for a dialog route the view is not blanked, so the list does not blink.
* **Ctrl/⌘+S saves**, in both surfaces.
* **A caller can name the return page** — the settings screen's trial button passes
  `returnTo: "#/settings"`, so closing the form goes back to Settings rather than to the person list.

Accessibility: `role="dialog"`, `aria-modal="true"`, `aria-labelledby` on the title,
`aria-describedby` when a description exists, the page behind is scroll-locked via a counter on
`body.modal-open` (nested dialogs included), and the mode cards are a real `role="radiogroup"` of
`role="radio"` buttons with `aria-checked`.

Responsive: below 960 px `auto` resolves to the page surface; the dialog itself is width-clamped and
its footer wraps. The suite checks both directions (1440 px → 1 dialog, 0 page forms; 700 px → 0
dialogs, 1 page form).

Bilingual: every string in the new surfaces comes from the locale files (`adm.formMode*`,
`rec.new`, `form.discard*`, …), 454 keys in each of `en.json` and `ar.json`, kept at parity by the
i18n assertions. In Arabic the dialog is RTL — head, footer order, close button and scrollbar side all
follow `dir`, with the screenshots in §8 taken in both languages.

---

## 5 · Where the code lives

| File | Responsibility |
|---|---|
| `app/migrations/007_ui_form_mode.sql` | seeds `ui.form_mode`, `ui.form_dialog_size` |
| `app/static/js/core.js` | `PREFS`/`pref`/`setPref`/`setting`/`formMode`/`formModeSource`, the rewritten `modal()` with `modalStack`, `MODAL_SIZES`, `focusables()`, `lockScroll()` |
| `app/static/js/views/record.js` | `formActions`, `confirmDiscard`, `replaceRoute`, `renderForm` (page), `openFormDialog` (dialog), `A.forms` |
| `app/static/js/app.js` | closes stray form dialogs on a route change; skips the skeleton for a dialog route |
| `app/static/js/views/admin.js` | the Settings card: mode cards, scope switch, width select, trial button |
| `app/static/js/views/{list,record}.js` | stamp `root.dataset.surface` |
| `app/static/css/{components,views}.css` | `.mode-*`, `.surface-row`, `.formbar.in-dialog`, dialog sizing |
| `app/db.py`, `app/repo.py` | `sync_sequence` / `peek_next_code` (see §6.1) |
| `/api/meta`, `/api/settings` | the instance default reaches the first paint |

---

## 6 · Three defects this phase found (and fixed)

Building the surface exercised paths that pages had been quietly hiding. All three are now covered by
tests.

### 6.1 · Save + New returned `409 Conflict` on the second save

*Symptom.* Preview a code (`PER-7228`), POST it, Save + New, preview again — still `PER-7228` — POST →
**409**, and the second record could not be created through the dialog at all.

*Cause.* `db.next_code` advances the sequence, but `repo.create_record` accepted a client-supplied
code and never told the sequence about it. The preview (`peek_next_code`) read the same stale counter,
so preview and save disagreed with the database.

*Fix.* `db.sync_sequence(conn, entity_type, code)` pushes `next_value` past any hand-supplied code
(`_CODE_TAIL` finds the numeric tail), `create_record` calls it when the payload carried a code, and
`peek_next_code` now skips codes that already exist so it agrees with `next_code`.

*Proof.* Three consecutive preview→POST cycles returned `PER-7228`, `PER-7229`, `PER-7230`, all
`200`; pinned by two pytest cases (`test_previewed_code_can_be_used_twice`,
`test_preview_skips_taken_codes`).

### 6.2 · Merge dropped links without telling anyone, and dropped the wrong ones

*Symptom.* Merging B into A could make a link disappear from the graph with no `change_log` entry, and
the duplicate test it used was `same side + same relationship type` — so a valid `B → Z` link was
deleted merely because `A → Y` existed with the same type, even when `Y ≠ Z`.

*Fix.* The clash test now compares **both ends and the type** (a duplicate is the same pair), links
that would become self-loops after the merge are dropped explicitly (`self_links_removed`), and every
decision is written to the change log:

```json
{"relationships_moved": 3, "duplicate_links_removed": 1, "self_links_removed": 1}
```

*Proof.* `tests/test_registry.py::test_merge_leaves_an_auditable_trail_for_links` builds all three
cases (exact duplicate, same-type-different-target, would-be self-link) and asserts both the counters
and the `change_log` rows.

### 6.3 · The duplicates panel put the cursor on "Merge", and merged on one click

*Symptom.* Opening "Duplicates" focused the first **Merge** button. A stray Enter — or a click — merged
two real records instantly, with no preview and no confirmation. (This is also how a probe left two
fixture rows merged during development; see §7.)

*Fix.* The dialog parks the cursor on its heading (`modal()` resolves `focus` against the whole
dialog, and the title carries `tabindex="-1"` for exactly this), and "Merge now" first shows exactly
what will happen — *"Will merge N → PER-xxxx"* — and asks for confirmation. `modal()` gained the
generic ability to focus a non-input element, which any future dialog can use.

---

## 7 · Data hygiene: what the harnesses used to leave behind

Found while reconciling the dataset after a full run: `verify_all.py::s_merge` and
`audit.py::s_graph` merge a scratch person into another, and a merge **soft-deletes** the absorbed
record — but the cleanup step only issued a hard delete, which cannot reach a soft-deleted row. Every
run therefore left a soft-deleted person behind, invisible to the marker sweep and to list views, and
the census drifted by one row per run.

Fixed in both harnesses: cleanup restores the id and *then* hard-deletes it, and the marker sweeps ask
for `include_deleted: true` so a merged scratch row cannot hide either. The audit's stray-row check
now explicitly looks at `deleted_at IS NOT NULL` as well.

Verified by running the full set twice: the census is **identical before and after** (28 538 active
records, 199 soft-deleted persons — the same 199 the checkpoint had), and `check-integrity` reports no
structural problems.

Two fixture rows were absorbed by the accidental merge in §6.3 during development. They were restored
via the audited `POST /api/person/{id}/restore`, and the eight fields the merge had filled on the
survivor were reverted to their shipped (blank) state with a change-log entry explaining why. Their
relationships had already been re-pointed onto the survivor by the merge, so `PER-4357` and `PER-5969`
are currently shells — recorded here rather than quietly patched, because inventing links to hide it
would be worse than documenting it. The product-side answer is a real one: **a merge should be
reversible from its own plan**, which is the natural next step for this area.

Relationship rows: 14 569 today against 14 572 at the phase-5 checkpoint. `REL-8593` and `REL-12595`
were exact duplicate links dropped by that merge; `REL-3547` is an older, pre-existing gap with no
change-log entry (relationship links were unlogged before §6.2). Nothing dangles: referential and
polymorphic integrity is clean.

---

## 8 · Screenshots

| File | Shows |
|---|---|
| `docs/screenshots/setting-form-surface.png` | the Settings card, three mode previews, scope switch, width, trial button |
| `docs/screenshots/form-dialog-en.png` | a person form as a dialog over a live list, English/LTR |
| `docs/screenshots/form-dialog-ar.png` | the same, Arabic/RTL |

---

## 9 · Verification

| Harness | Before phase 6 | Now |
|---|---|---|
| `pytest tests -q` | 90 | **94 passed** |
| `tests/verify_all.py` | 207 | **207 / 207** |
| `tests/ui_smoke.py` | 46 | **46 / 46** |
| `tests/ui_full.py` | 161 | **185 / 185** (24 new surface checks) |
| `tests/audit.py` | 162 | **162 / 162** |
| `ruff check .` | clean | clean |
| **total assertions** | 666 | **694** |

The 24 new interface checks cover: the settings card renders with the active mode marked; choosing a
mode persists and takes effect; page mode really renders a page and no dialog; dialog mode opens over a
list without repainting it, with focus inside and `aria-labelledby` set; Escape on a clean form returns
to the list; Escape on a dirty form offers "Discard changes?" and declining keeps the draft; saving
lands on the dossier; Save + New reuses the surface with a cleared form; editing opens over the dossier
with the dossier still visible; the trial button returns to `#/settings`; the auto threshold renders a
dialog at 1440 px and a page at 700 px; RTL keeps the footer and close button in the right place.

## 10 · Decided limits

* **Import, bulk edit and settings stay pages.** Stated above; happy to revisit for the import wizard's
  review step if a two-step "confirm the rows" pass is ever wanted.
* **`auto` breaks at 960 px.** One number in one place (`formMode()`), chosen so a 1024-px laptop gets
  the dialog and a tablet in portrait gets the page.
* **The dialog is not resizable or draggable.** Deliberate: a draggable modal is a page you have to
  manage. Width is a setting; position is not a conversation.
* **A merge is not yet reversible from the UI.** Its plan is now fully recorded (including dropped
  links), which is the prerequisite for an "undo merge" action — the honest follow-up, not a claim.
