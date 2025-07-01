/** @odoo-module **/
import { FormController } from "@web/views/form/form_controller";
import { formView } from "@web/views/form/form_view";
import { registry } from "@web/core/registry";

class SaccoMemberFormController extends FormController {
    setup() {
        super.setup();
    }

    async updateMemberDetails() {
        const record = this.model.root;
        await this.model.root.save();
        await this.model.env.services.orm.call(
            "res.partner",
            "update_member_details",
            [[record.resId]]
        );
        await record.load();
        this.env.services.notification.add(this.env._t("Member details updated successfully"), {
            type: "success",
        });
    }
}

SaccoMemberFormController.template = "web.FormView";

export const SaccoMemberFormView = {
    ...formView,
    Controller: SaccoMemberFormController,
};

registry.category("views").add("sacco_member_form", SaccoMemberFormView);