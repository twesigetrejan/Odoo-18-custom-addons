/** @odoo-module **/

import { FormController } from "@web/views/form/form_controller";
import { patch } from "@web/core/utils/patch";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";

patch(FormController.prototype, "member_management.FormController", {
    async saveRecord() {
        const model = this.model.root;
        if (model.resModel === 'res.partner' && model.data.is_sacco_member) {
            const confirmed = await new Promise(resolve => {
                Dialog.confirm(this, _t("Do you really want to save the details?"), {
                    confirm_callback: () => resolve(true),
                    cancel_callback: () => resolve(false),
                });
            });
            if (!confirmed) {
                return false;
            }
        }
        return this._super(...arguments);
    },

    async _onSave(ev) {
        const model = this.model.root;
        if (model.resModel === 'res.partner' && model.data.is_sacco_member) {
            ev.stopPropagation();
            const confirmed = await new Promise(resolve => {
                Dialog.confirm(this, _t("Do you really want to update the details?"), {
                    confirm_callback: () => resolve(true),
                    cancel_callback: () => resolve(false),
                });
            });
            if (!confirmed) {
                return;
            }
        }
        return this._super(...arguments);
    },
});