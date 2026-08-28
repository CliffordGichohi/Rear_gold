# Gold Auction Automation Matched-Replay Verification Shutdown Correction

## Scope

After the completed audit had written and sealed every result artifact, process shutdown emitted an event-loop connection-close warning. The cause was disposal of the asynchronous database engine through a second `asyncio.run` event loop.

The script now evaluates the audit and disposes the engine on the same event loop. This correction changes no detector definition, source, population, marking row, proposal, trade, outcome, metric, verdict or sealed result artifact.

## Audit trail

- Result-producing script SHA-256: `a9d0a8050a07175d905805a39c590e83d27f47dc3bbc475b1d94535964464322`
- Shutdown-corrected script SHA-256: `679336123521dd704efecd5a4e28dccc19f4e27ac9aee1188f3f6f5b1a380a2c`
- Syntax compilation after correction: `PASS`
- Expensive result rerun: not performed because the correction executes only after evaluation and cannot affect any sealed result

