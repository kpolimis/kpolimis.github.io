.PHONY: help preview render clean

help:
	@echo "Usage:"
	@echo "  make preview  - Start local dev server with hot-reloading"
	@echo "  make render   - Build site to _site/"
	@echo "  make clean    - Remove generated files"

preview:
	quarto preview

render:
	quarto render

clean:
	rm -rf _site
	rm -rf .quarto
