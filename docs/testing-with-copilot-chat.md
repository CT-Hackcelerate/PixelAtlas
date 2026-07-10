# Testing with Copilot Chat

Once the venv is set up and Orthanc is running, you can test the read-only tools via Copilot Chat:

**Prerequisites:**
- VS Code with GitHub Copilot Chat extension installed and signed in
- Copilot **Agent Mode** enabled (org policy controlled — check Copilot settings)
- **MCP Servers** enabled in Copilot settings (usually enabled by default once Agent Mode is on)

**Steps:**

1. **Reload VS Code** to pick up the MCP server registration from `.vscode/mcp.json`:
   - Press `Ctrl+R` or go to View → Command Palette → "Developer: Reload Window"
   - You should see the MCP server start (check the Output panel, Copilot channel, for any errors)

2. **Open Copilot Chat**:
   - Press `Ctrl+Shift+I` or click the Copilot Chat icon in the Activity Bar

3. **Switch to the Pixel Atlas chat mode** (dropdown at the top of the Chat panel):
   - Click the mode selector and choose **Pixel Atlas**
   - This restricts the available tools to `pixel-atlas/*` only

4. **Test the read-only commands**:

   ```
   /list-templates
   ```
   Expected: a table with the four generic IOD templates we've implemented — `ct-image` (CT), `mr-image` (MR), `us-image` (US), `mg-image` (MG) — each with blank `body_part`/`orientation` (generic, IOD-level) and `has_seed_data` (true).

   ```
   /status
   ```
   Expected: a status table showing:
   - `mcp_server`: ok
   - `orthanc_reachable`: true (with Orthanc version and URL)
   - `dcmtk_binaries_on_path`: `dcmodify`/`storescu`/`findscu`/`dcmftest` true, `dciodvfy` false (expected — IOD conformance is covered by `dicom-validator` instead, see [implementation-status.md](implementation-status.md#phase-3--complete-script-level-copilot-chat-run-through-still-pending))
   - `template_count`: 4 (one generic IOD template each for CT/MR/US/MG)

   ```
   /status job=does-not-exist
   ```
   Expected: an error message saying no job found with that id (since the job registry is empty until a `/generate` job populates it).

5. **Test generation** (make sure DCMTK's `bin` folder, e.g.
   `C:\tools\dcmtk-3.7.0-win64-dynamic\bin`, is on PATH before launching VS Code
   so `storescu` is available to the MCP server process):

   ```
   /generate modality=CT count=3 orientation=axial body_part=CHEST
   ```
   Expected: since Orthanc has no CHEST/axial CT data yet, the agent reports no
   PACS match and asks to confirm falling back to the `ct-image` template
   seed (CT Image IOD, generic — CHEST/axial come from the requested
   overrides). On confirmation, it generates 3 instances and validates them (reporting
   `passed: true` with `iod_conformance.files_with_errors: 0`), then — **before
   storing anything** — shows a summary and asks you to confirm the store.
   Only after that confirmation does it call `store_to_pacs(..., confirm_store=True)`
   and summarize job_id/study_uid/stored_count. This store confirmation
   happens on every `/generate` call, not just large ones.

   ```
   /generate modality=CT count=200 orientation=axial body_part=CHEST
   ```
   Expected: same as above, plus an explicit >50-instance confirmation prompt
   before generation starts.

   ```
   /generate modality=CT count=2 prior_of=<study_uid from the previous /generate> days_before=90
   ```
   Expected: the agent generates 2 instances that share the referenced study's
   `PatientID` and have a `StudyDate` 90 days earlier, with their own new
   `StudyInstanceUID`. The summary should call out the shared PatientID and
   computed StudyDate explicitly.

6. **Test the generic PACS feature lookup** (natural language, or the
   `/check-feature` slash command — see the troubleshooting note below on
   why the slash-command form is more reliable):

   ```
   Do we have any CT study with a Modality LUT?
   ```
   Expected: the agent recognizes "Modality LUT" as `ModalityLUTSequence`
   (tag `0028,3000`) itself, calls `check_pacs_feature(tag="ModalityLUTSequence", modality="CT")`,
   and reports 0 matches (none of our synthetic seeds include one).

   ```
   Is there a study where RescaleSlope is 1?
   ```
   Expected: the agent calls `check_pacs_feature(tag="RescaleSlope", value="1")`
   and reports the matching studies (should exclude the one pre-existing real
   study that lacks `RescaleSlope`).

**Troubleshooting:**

| Problem | Check |
|---|---|
| Chat mode dropdown doesn't show Pixel Atlas | `.github/chatmodes/pixel-atlas.chatmode.md` exists and is valid YAML; try reloading VS Code |
| "MCP server not found" error in chat | Check Copilot Output panel (View → Output → Copilot) for stderr from the server; verify `.vscode/mcp.json` path is correct |
| `/list-templates` times out or returns empty | Check `mcp-server/server.py` starts without error: `.venv\Scripts\python mcp-server\server.py` (Ctrl+C to exit); verify `templates/catalog.yaml` exists |
| `/status` shows `orthanc_reachable: false` | Verify Orthanc container is running (`docker ps`) and listening on `localhost:8042`; check `ORTHANC_URL`/`ORTHANC_USER`/`ORTHANC_PASSWORD` in `.vscode/mcp.json` match your setup |
| `store_to_pacs` reports `method: orthanc_rest` instead of `storescu` | `storescu` isn't on PATH for the process VS Code launched the MCP server from — add DCMTK's `bin` folder to the system/user PATH (not just the current shell) and reload VS Code |
| Agent says a tool (e.g. `check_pacs_feature`) "is not available in this session", or loops calling an unrelated tool (e.g. `get_job_status` with a made-up job id) instead of the one it needs | Fully **restart** VS Code (not just "Reload Window") and start a **new** chat conversation — a stale session can cache an older tool list. Verify in the chat's tools picker (wrench icon) that the tool is checked/enabled for the `pixel-atlas` server. If it's still missing, check View → Output → the MCP output channel for the actual `tools/list` response. Prefer the slash-command form (e.g. `/check-feature`) over free-form phrasing when this happens — slash commands scope the model to only the tools that command needs, which is what actually prevents the wandering. |
| Agent maps your phrase to the wrong DICOM tag (e.g. treats "Modality LUT" as `RescaleSlope`) | This was a real bug in `pixel-atlas.chatmode.md`'s own wording (two unrelated example tags mentioned in the same sentence, which the model conflated) — fixed, but if you see it recur with a different tag pair, it's the same class of issue: report which phrase/tag pair, so the chatmode instructions can be tightened further. |
