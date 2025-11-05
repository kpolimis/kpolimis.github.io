#!/usr/bin/env python
# -*- coding: utf-8 -*- #
from __future__ import unicode_literals
import os
#from utils import filters

AUTHOR = u'Kivan Polimis'
SITENAME = u'Kivan Polimis'
# SITESUBTITLE = u'my personal musings and attempts to apply \
# and share some programming tips'

INDEX_SAVE_AS = 'pages/home.html'
PATH = 'content'
PAGE_ORDER_BY = 'sortorder'

# Times and dates
TIMEZONE = 'US/Central'
DEFAULT_LANG = u'en'

SUMMARY_MAX_LENGTH = '50'
GOOGLE_ANALYTICS = 'UA-104881568-1'

# Set the article URL
#ARTICLE_URL = 'blog/{date:%Y}/{date:%m}/{date:%d}/{slug}/'
#ARTICLE_SAVE_AS = 'blog/{date:%Y}/{date:%m}/{date:%d}/{slug}/index.html'

# Theme and plugins
# JINJA_FILTERS = {'sidebar': filters.sidebar}
THEME = "pelican-themes/nest"

# Minified CSS
NEST_CSS_MINIFY = True
# Add canonical link element to top page header and all article/author/category/tag page header
NEST_REL_CANONICAL_LINK = True

NEST_HEADER_IMAGES = ''
NEST_HEADER_LOGO = '/images/jade_mountain.png'

DISPLAY_PAGES_ON_MENU = False
# MENUITEMS = [('Home', '/index.html'), ('Articles', '/categories.html')]
MENUITEMS = [('Home', '/index.html'),('Articles','/pages/categories.html'),
('Vita','/pages/vita.html'),('Teaching','/pages/teaching.html'), 
 ('Software','/pages/software.html'), ('Projects','/pages/projects.html')]

# categories.html
NEST_CATEGORIES_HEAD_TITLE = u'Articles'
NEST_CATEGORIES_HEAD_DESCRIPTION = u'Articles listed by category'
NEST_CATEGORIES_HEADER_TITLE = u'Articles'
NEST_CATEGORIES_HEADER_SUBTITLE = u'Articles listed by category'


# Footer
NEST_SITEMAP_COLUMN_TITLE = u'Sitemap'
NEST_SITEMAP_MENU = [('Home', '/index.html'),('Articles','pages/categories.html'),
('Vita','/pages/vita.html'),('Teaching','/pages/teaching.html'), 
 ('Software','/pages/software.html'), ('Projects','/pages/projects.html')]
NEST_SITEMAP_ATOM_LINK = u'Atom Feed'
NEST_SITEMAP_RSS_LINK = u'RSS Feed'
NEST_SOCIAL_COLUMN_TITLE = u'Social'
NEST_LINKS_COLUMN_TITLE = u'Links'
NEST_COPYRIGHT = u'&copy; Kivan Polimis 2025'

# pagination.html
NEST_PAGINATION_PREVIOUS = u'Previous'
NEST_PAGINATION_NEXT = u'Next'

# Footer optional
NEST_FOOTER_HTML = ''

# Static files
STATIC_PATHS = ['images',  'favicon.ico']

CODE_DIR = 'downloads/code'
NOTEBOOK_DIR = 'downloads/notebooks'

READERS = {'html': None}
PLUGIN_PATHS = ['pelican-plugins']
PLUGINS = ['liquid_tags.notebook',  # for embedding notebooks
           'summary',       # auto-summarizing articles
           'feed_summary',  # use summaries for RSS, not full articles
           'render_math'
           ]

MD = ['codehilite(css_class=highlight)','extra', 'mathjax']
# Only use LaTeX for selected articles

LATEX = 'article'

# SUMMARY_USE_FIRST_PARAGRAPH = 'True'

TWITTER_USERNAME = 'kpolimis'
GITHUB_USERNAME = 'kpolimis'
AUTHOR_CV = "http://kivanpolimis.com/docs/Kivan_Polimis_Curriculum_Vitae.pdf"
SHOW_ARCHIVES = True

IGNORE_FILES = ['.ipynb_checkpoints']

if not os.path.exists('_nb_header.html'):
    import warnings
    warnings.warn("_nb_header.html not found.  "
                  "Rerun make html to finalize build.")
else:
    EXTRA_HEADER = open('_nb_header.html').read()

# RMD_READER_KNITR_OPTS_CHUNK = {'fig.path': '../../../figure/'}


# Feed generation is usually not desired when developing
FEED_ALL_ATOM = None
CATEGORY_FEED_ATOM = None
TRANSLATION_FEED_ATOM = None
AUTHOR_FEED_ATOM = None
AUTHOR_FEED_RSS = None

# Title menu options

DEFAULT_PAGINATION = 10

# Uncomment following line if you want document-relative URLs when developing
RELATIVE_URLS = True

# Blogroll
#LINKS = (('Pelican', 'http://getpelican.com/'),
#         ('Python.org', 'http://python.org/'),
#         ('Jinja2', 'http://jinja.pocoo.org/'),
#         ('You can modify those links in your config file', '#'),)

# Social widget
#SOCIAL = (('You can add links in your config file', '#'),
#          ('Another social link', '#'),)
