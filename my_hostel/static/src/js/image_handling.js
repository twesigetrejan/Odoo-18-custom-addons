odoo.define('my_hostel.image_handling', function (require) {
    "use strict";
    
    var FormController = require('web.FormController');
    
    FormController.include({
        _onUpload: function (ev) {
            var file = ev.target.files[0];
            if (file && file.size > 25 * 1024 * 1024) {
                ev.preventDefault();
                this.do_warn("File too large", "Maximum image size is 25MB");
                return;
            }
            return this._super.apply(this, arguments);
        },
    });
});