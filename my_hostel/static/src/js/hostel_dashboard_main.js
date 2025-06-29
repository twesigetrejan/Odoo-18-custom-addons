/** @odoo-module **/

import { Component, onWillStart, useState } from '@odoo/owl';
import { registry } from '@web/core/registry';
import { useService } from '@web/core/utils/hooks';

export class HostelDashboardMain extends Component {
    setup() {
        super.setup();
        this.rpc = useService('rpc'); // Ensure this resolves the RPC service
        console.log('RPC Service:', this.rpc); // Debug to check if rpc is defined
        this.state = useState({
            total_hostels: 0,
            total_rooms: 0,
            total_students: 0,
            total_rent: 0.0,
        });

        onWillStart(async () => {
            if (this.rpc && typeof this.rpc.query === 'function') {
                try {
                    const data = await this.rpc.query({
                        model: 'hostel.dashboard',
                        method: 'get_overview_metrics',
                        args: [],
                    });
                    this.state.total_hostels = data.total_hostels || 0;
                    this.state.total_rooms = data.total_rooms || 0;
                    this.state.total_students = data.total_students || 0;
                    this.state.total_rent = data.total_rent || 0.0;
                } catch (error) {
                    console.error('RPC Error:', error);
                }
            } else {
                console.error('RPC service not available');
            }
        });
    }
}

HostelDashboardMain.template = 'my_hostel.HostelDashboardMainTemplate';

registry.category('actions').add('hostel_dashboard_main', HostelDashboardMain);

// /** @odoo-module **/

// import { Component, onWillStart, useState } from '@odoo/owl';
// import { registry } from '@web/core/registry';
// import { useService } from '@web/core/utils/hooks';

// export class HostelDashboardMain extends Component {
//     setup() {
//         super.setup();
//         this.rpc = useService('rpc');
//         this.state = useState({
//             total_hostels: 0,
//             total_rooms: 0,
//             total_students: 0,
//             total_rent: 0.0,
//         });

//         onWillStart(async () => {
//             const data = await this.rpc.query({
//                 model: 'hostel.dashboard',
//                 method: 'get_overview_metrics',
//                 args: [],
//             });
//             this.state.total_hostels = data.total_hostels;
//             this.state.total_rooms = data.total_rooms;
//             this.state.total_students = data.total_students;
//             this.state.total_rent = data.total_rent;
//         });
//     }
// }

// HostelDashboardMain.template = 'my_hostel.HostelDashboardMainTemplate';

// registry.category('actions').add('hostel_dashboard_main', HostelDashboardMain);
