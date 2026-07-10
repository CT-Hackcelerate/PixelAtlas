Pixel Atlas generates/modifies synthetic DICOM test data via the local
`pixel-atlas` MCP server, storing results in a local Orthanc PACS. Never
invent DICOM tag values — use the `pixel-atlas` MCP tools. Always check the
PACS for similar existing data before falling back to bundled template seed
data, and never use the fallback without explicit user confirmation. Never
generate real PHI. Confirm before any operation affecting more than 50
instances or any in-place PACS overwrite. See docs/solution-design.md and
docs/architecture.md for full design.
