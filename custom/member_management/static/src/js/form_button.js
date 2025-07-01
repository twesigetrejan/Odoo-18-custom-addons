/** @odoo-module **/
import { FormController } from "@web/views/form/form_controller";
import { formView } from '@web/views/form/form_view';
import { registry } from '@web/core/registry';
import { useService } from "@web/core/utils/hooks";

class MemberFormController extends FormController {
    setup() {
        super.setup();
        this.orm = useService("orm");
    }

    onUpdateClick() {
        const recordId = this.model.root.resId;
        
        this.orm.call("res.partner", "update_member_details", [[recordId]])
            .then(() => {
                this.model.root.load();
            })
            .catch((error) => {
                console.error("Error updating member details:", error);
            });
    }
}

MemberFormController.template = 'member_management.FormView.Buttons';

export const memberFormView = {
    ...formView,
    Controller: MemberFormController,
};

registry.category("views").add("member_form", memberFormView);