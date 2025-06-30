/** @odoo-module **/

import { Component, onWillStart, onMounted, useState, useRef } from '@odoo/owl';
import { registry } from '@web/core/registry';
import { useService } from '@web/core/utils/hooks';
import { loadJS } from '@web/core/assets';

export class HostelDashboardMain extends Component {
    setup() {
        super.setup();
        this.orm = useService('orm');
        this.action = useService('action');
        console.log('ORM Service:', this.orm);
        this.state = useState({
            total_hostels: 0,
            total_rooms: 0,
            total_students: 0,
            total_rent: 0.0,
            total_amenities: 0,
            avg_rent: 0.0,
            occupancy_rate: 0.0,
            occupied_rooms: 0,
            avg_room_occupancy_rate: 0.0,
            most_common_amenity: '',
            unpaid_rent: 0.0,
            unpaid_rent_data: [],
            error: null,
        });
        this.barChartRef = useRef('barChart');
        this.doughnutChartRef = useRef('doughnutChart');
        this.lineChartRef = useRef('lineChart');

        onWillStart(async () => {
            await this.loadExternalLibraries();
            await this.fetchDashboardData();
        });

        onMounted(() => {
            console.log('Bar chart element:', this.barChartRef.el);
            console.log('Doughnut chart element:', this.doughnutChartRef.el);
            console.log('Line chart element:', this.lineChartRef.el);
            this.renderCharts();
        });
    }

    async loadExternalLibraries() {
        const libraries = [
            'https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js',
        ];
        for (const lib of libraries) {
            try {
                console.log(`Loading ${lib}...`);
                await loadJS(lib);
                console.log(`${lib} loaded successfully`);
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
            this.state.total_amenities = data.total_amenities || 0;
            this.state.avg_rent = data.avg_rent || 0.0;
            this.state.occupancy_rate = data.occupancy_rate || 0.0;
            this.state.occupied_rooms = data.occupied_rooms || 0;
            this.state.avg_room_occupancy_rate = data.avg_room_occupancy_rate || 0.0;
            this.state.most_common_amenity = data.most_common_amenity || '';
            this.state.unpaid_rent = data.unpaid_rent || 0.0;
            this.state.unpaid_rent_data = data.unpaid_rent_data || [];
        } catch (error) {
            console.error('Error fetching dashboard data:', error);
            this.state.error = 'Failed to fetch data: ' + error.message;
        }
    }

    renderCharts() {
        // Bar Chart: Occupied Rooms vs Total Rooms vs Total Students
        if (this.barChartRef.el) {
            const barCtx = this.barChartRef.el.getContext('2d');
            if (this.state.barChart) this.state.barChart.destroy();
            this.state.barChart = new Chart(barCtx, {
                type: 'bar',
                data: {
                    labels: ['Occupied Rooms', 'Total Rooms', 'Total Students'],
                    datasets: [{
                        label: 'Counts',
                        data: [
                            this.state.occupied_rooms,
                            this.state.total_rooms,
                            this.state.total_students,
                        ],
                        backgroundColor: ['#FF6384', '#36A2EB', '#FFCE56'],
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: { y: { beginAtZero: true } },
                    plugins: { legend: { position: 'top' } },
                    layout: { padding: 10 },
                    height: 150,
                    width: 300,
                },
            });
        } else {
            console.error('Bar chart element not found');
        }

        // Doughnut Chart: Average Room Occupancy Rate
        if (this.doughnutChartRef.el) {
            const doughnutCtx = this.doughnutChartRef.el.getContext('2d');
            if (this.state.doughnutChart) this.state.doughnutChart.destroy();
            this.state.doughnutChart = new Chart(doughnutCtx, {
                type: 'doughnut',
                data: {
                    labels: ['Occupied', 'Unoccupied'],
                    datasets: [{
                        data: [
                            this.state.avg_room_occupancy_rate,
                            100 - this.state.avg_room_occupancy_rate,
                        ],
                        backgroundColor: ['#36A2EB', '#FFCE56'],
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { position: 'top' } },
                    layout: { padding: 10 },
                    height: 150,
                    width: 300,
                },
            });
        } else {
            console.error('Doughnut chart element not found');
        }

        // Line Chart: Unpaid Rent Over Time
        if (this.lineChartRef.el) {
            const lineCtx = this.lineChartRef.el.getContext('2d');
            if (this.state.lineChart) this.state.lineChart.destroy();
            this.state.lineChart = new Chart(lineCtx, {
                type: 'line',
                data: {
                    labels: this.state.unpaid_rent_data.map(item => item.date.toISOString().split('T')[0]),
                    datasets: [{
                        label: 'Unpaid Rent (UGX)',
                        data: this.state.unpaid_rent_data.map(item => item.amount),
                        borderColor: '#FF6384',
                        fill: false,
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        x: { type: 'time', time: { unit: 'day' } },
                        y: { beginAtZero: true },
                    },
                    plugins: { legend: { position: 'top' } },
                    layout: { padding: 10 },
                    height: 150,
                    width: 300,
                },
            });
        } else {
            console.error('Line chart element not found');
        }
    }

    downloadReport() {
        try {
            console.log('Triggering PDF report download...');
            this.orm.call('hostel.dashboard', 'generate_pdf_report', []).then(action => {
                if (action) this.action.doAction(action);
            }).catch(error => {
                console.error('Download Error:', error);
            });
        } catch (error) {
            console.error('Download failed:', error);
        }
    }
}

HostelDashboardMain.template = 'my_hostel.HostelDashboardMainTemplate';

registry.category('actions').add('hostel_dashboard_main', HostelDashboardMain);