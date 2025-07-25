================
Partner Property
================

.. 
   !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
   !! This file is generated by oca-gen-addon-readme !!
   !! changes will be overwritten.                   !!
   !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
   !! source digest: sha256:4936bf86b2b9584bbd22aa43279c16621a838c03844726645ccec006f528c900
   !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

.. |badge1| image:: https://img.shields.io/badge/maturity-Beta-yellow.png
    :target: https://odoo-community.org/page/development-status
    :alt: Beta
.. |badge2| image:: https://img.shields.io/badge/licence-AGPL--3-blue.png
    :target: http://www.gnu.org/licenses/agpl-3.0-standalone.html
    :alt: License: AGPL-3
.. |badge3| image:: https://img.shields.io/badge/github-OCA%2Fpartner--contact-lightgray.png?logo=github
    :target: https://github.com/OCA/partner-contact/tree/17.0/partner_property
    :alt: OCA/partner-contact
.. |badge4| image:: https://img.shields.io/badge/weblate-Translate%20me-F47D42.png
    :target: https://translation.odoo-community.org/projects/partner-contact-17-0/partner-contact-17-0-partner_property
    :alt: Translate me on Weblate
.. |badge5| image:: https://img.shields.io/badge/runboat-Try%20me-875A7B.png
    :target: https://runboat.odoo-community.org/builds?repo=OCA/partner-contact&target_branch=17.0
    :alt: Try me on Runboat

|badge1| |badge2| |badge3| |badge4| |badge5|

This module adds the use of properties in partners (different for
companies and individuals).

**Table of contents**

.. contents::
   :local:

Usage
=====

Add property fields:

1. Go to Contacts and create or edit any record.
2. Click ⚙ Add Properties ‣ Field Type, select the type and add a
   default value if needed. To make the fields appear in kanban views,
   check View in Kanban as well. To validate and close the property
   creation window, click anywhere.
3. The properties that will be displayed will be different for
   Individual or Company.

Delete property fields:

1. Click the pencil icon next to the targeted property, then click
   Delete ‣ Delete.

Known issues / Roadmap
======================

- The properties are shared between all the companies accessing the
  contact, as the properties fields in the ORM are very limited in
  possibilities (they don't admit compute methods for example).
- The properties definition is stored in the system parameter
  partner_property.properties_definition. Don't touch its value manually
  for not breaking the definition or losing data.

Bug Tracker
===========

Bugs are tracked on `GitHub Issues <https://github.com/OCA/partner-contact/issues>`_.
In case of trouble, please check there if your issue has already been reported.
If you spotted it first, help us to smash it by providing a detailed and welcomed
`feedback <https://github.com/OCA/partner-contact/issues/new?body=module:%20partner_property%0Aversion:%2017.0%0A%0A**Steps%20to%20reproduce**%0A-%20...%0A%0A**Current%20behavior**%0A%0A**Expected%20behavior**>`_.

Do not contact contributors directly about support or help with technical issues.

Credits
=======

Authors
-------

* Tecnativa

Contributors
------------

- `Tecnativa <https://www.tecnativa.com>`__:

  - Víctor Martínez
  - Pedro M. Baeza
  - Pilar Vargas

Maintainers
-----------

This module is maintained by the OCA.

.. image:: https://odoo-community.org/logo.png
   :alt: Odoo Community Association
   :target: https://odoo-community.org

OCA, or the Odoo Community Association, is a nonprofit organization whose
mission is to support the collaborative development of Odoo features and
promote its widespread use.

.. |maintainer-victoralmau| image:: https://github.com/victoralmau.png?size=40px
    :target: https://github.com/victoralmau
    :alt: victoralmau

Current `maintainer <https://odoo-community.org/page/maintainer-role>`__:

|maintainer-victoralmau| 

This module is part of the `OCA/partner-contact <https://github.com/OCA/partner-contact/tree/17.0/partner_property>`_ project on GitHub.

You are welcome to contribute. To learn how please visit https://odoo-community.org/page/Contribute.
