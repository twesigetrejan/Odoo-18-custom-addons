/** @odoo-module **/

import { Component, onWillStart, onMounted, useState, useRef } from '@odoo/owl';
import { registry } from '@web/core/registry';
import { useService } from '@web/core/utils/hooks';
import { loadJS } from '@web/core/assets';

export class HostelDashboardMain extends Component {
    setup() {
        super.setup();
        this.orm = useService('orm'); // Use orm service
        this.action = useService('action'); // For potential future actions
        console.log('ORM Service:', this.orm); // Debug orm service
        this.state = useState({
            total_hostels: 0,
            total_rooms: 0,
            total_students: 0,
            total_rent: 0.0,
            error: null,
        });
        this.chartRef = useRef('chart');

        onWillStart(async () => {
            await this.loadExternalLibraries();
            await this.fetchDashboardData();
        });

        onMounted(() => {
            console.log('Chart element:', this.chartRef.el);
            this.renderChart();
        });
    }

    async loadExternalLibraries() {
        const libraries = [
            'https://cdn.jsdelivr.net/npm/chart.js', // Match your manifest CDN
        ];
        for (const lib of libraries) {
            try {
                await loadJS(lib);
            } catch (error) {
                console.error(`Failed to load ${lib}:`, error);
                throw new Error(`Failed to load required library: ${lib}`);
            }
        }
    }

    async fetchDashboardData() {
        try {
            console.log('Fetching dashboard data...');
            const data = await this.orm.call('hostel.dashboard', 'get_overview_metrics', []);
            console.log('Dashboard data:', data);
            this.state.total_hostels = data.total_hostels || 0;
            this.state.total_rooms = data.total_rooms || 0;
            this.state.total_students = data.total_students || 0;
            this.state.total_rent = data.total_rent || 0.0;
        } catch (error) {
            console.error('Error fetching dashboard data:', error);
            this.state.error = 'Failed to fetch data: ' + error.message;
        }
    }

    renderChart() {
        if (this.chartRef.el) {
            const ctx = this.chartRef.el.getContext('2d');
            if (this.state.chartData) this.state.chartData.destroy();
            this.state.chartData = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: ['Hostels', 'Rooms', 'Students'],
                    datasets: [{
                        label: 'Totals',
                        data: [this.state.total_hostels, this.state.total_rooms, this.state.total_students],
                        backgroundColor: ['#FF6384', '#36A2EB', '#FFCE56'],
                    }],
                },
                options: {
                    scales: { y: { beginAtZero: true } },
                    plugins: { legend: { position: 'top' } },
                },
            });
        } else {
            console.error('Chart element not found');
        }
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
//         this.rpc = useService('rpc'); // Ensure this resolves the RPC service
//         console.log('RPC Service:', this.rpc); // Debug to check if rpc is defined
//         this.state = useState({
//             total_hostels: 0,
//             total_rooms: 0,
//             total_students: 0,
//             total_rent: 0.0,
//         });

//         onWillStart(async () => {
//             if (this.rpc && typeof this.rpc.query === 'function') {
//                 try {
//                     const data = await this.rpc.query({
//                         model: 'hostel.dashboard',
//                         method: 'get_overview_metrics',
//                         args: [],
//                     });
//                     this.state.total_hostels = data.total_hostels || 0;
//                     this.state.total_rooms = data.total_rooms || 0;
//                     this.state.total_students = data.total_students || 0;
//                     this.state.total_rent = data.total_rent || 0.0;
//                 } catch (error) {
//                     console.error('RPC Error:', error);
//                 }
//             } else {
//                 console.error('RPC service not available');
//             }
//         });
//     }
// }

// HostelDashboardMain.template = 'my_hostel.HostelDashboardMainTemplate';

// registry.category('actions').add('hostel_dashboard_main', HostelDashboardMain);

