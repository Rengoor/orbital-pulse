# earth/ — Earth base display

Ground oversight. Open `index.html`. Everything the vehicle has recorded, and
the tools to check it:

- **Decision log**: every record, filterable by crew and tier.
- **Selected decision**: the Checker's explanation, each pipeline's assessment,
  data quality, which gate changed the tier, and the decision environment
  (hashes, key, versions). Verify the chain, replay the decision, record a review.
- **Chain integrity**: verify the whole chain; save a checkpoint and check the
  chain against it later to catch removed or rewritten records.
- **Downlink log**: what is queued on the vehicle and what Earth has received,
  for a chosen link delay.
- **Review log**: every ground review, in its own signed chain.

This page decides nothing: it shows what the backend recorded and calls the
backend to verify. With no link it shows no data, never sample data.

Shared styles and components come from `../css` and `../js`.
