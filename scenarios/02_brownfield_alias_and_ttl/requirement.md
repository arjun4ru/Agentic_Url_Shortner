# Scenario 2 (Brownfield): Add Custom Aliases and Link Expiration

Type: brownfield

On top of the existing URL shortener (built in Scenario 1), we now want two
enhancements:

1. Let users pick their own short code instead of always getting an
   auto-generated one (a "custom alias").
2. Let users optionally set an expiration time for a link, after which it
   should stop working.

This must not break any of the existing shorten/redirect/analytics behavior
for links that don't use these new options.
