

## Contact accuracy and exports

Website guesses require the business name and matching phone or address evidence.
Records with conflicting phones or addresses are kept separate. Guessed email
addresses remain labeled **Guessed** after DNS verification: a mail-enabled domain
does not confirm that a mailbox exists.

Export CSV writes one contractor per row with source URLs, discovery time,
confidence, email acquisition method, and verification status. Export Board CSV
retains the grouped board layout. CSV saves replace the destination atomically.
Search radius values are miles in the interface and meters internally; OSM
fallback results are filtered by distance. Other provider searches use their
location or bias controls and may return businesses outside that radius.

Stop cancels queued enrichment and interruptible retry delays. An active
synchronous HTTP or browser request may finish its timeout before stopping.
Results already displayed are retained. Search and verification cannot overlap;
closing waits for active workers to finish.

## Development checks

Install `requirements.txt` and run `QT_QPA_PLATFORM=offscreen pytest tests/ -v`
(on Windows, set the environment variable before invoking pytest).
CI checks formatting, real Qt and parser dependencies, source GUI startup, and
the frozen Windows application. The Windows build artifact is available from
the successful CI run. `--smoke-test` exits the GUI automatically and skips
first-run browser installation.
