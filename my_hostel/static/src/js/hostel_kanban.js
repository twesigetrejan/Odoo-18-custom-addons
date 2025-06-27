

odoo.define('my_hostel.hostel_kanban', function (require) {
"use strict";

var KanbanRecord = require('web.KanbanRecord');

KanbanRecord.include({
    
    _stripHtml: function(html) {
        if (!html) return '';
        return html.replace(/<[^>]*>/g, '');
    },
});

});