/** @odoo-module **/

import { Component, onWillStart, onMounted, useState, useRef } from '@odoo/owl';
import { registry } from '@web/core/registry';
import { useService } from '@web/core/utils/hooks';
import { loadJS } from '@web/core/assets';

export class LoanDashboardMain extends Component {
    setup() {
        super.setup();
        this.orm = useService('orm');
        this.action = useService('action');
        console.log('ORM Service:', this.orm);
        this.state = useState({
            total_disbursed: 0,
            expected_outstanding: 0,
            actual_outstanding: 0,
            loan_count: 0,
            error: null,
            loanDetails: [],
        });
        this.barChartRef = useRef('barChart');

        onWillStart(async () => {
            await this.loadExternalLibraries();
            await this.fetchDashboardData();
            await this.fetchLoanDetails();
        });

        onMounted(() => {
            console.log('Bar chart element:', this.barChartRef.el);
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
            const data = await this.orm.call('loan.portfolio', 'get_overview_metrics', []);
            console.log('Dashboard data:', data);
            this.state.total_disbursed = data.total_disbursed || 0;
            this.state.expected_outstanding = data.expected_outstanding || 0;
            this.state.actual_outstanding = data.actual_outstanding || 0;
            this.state.loan_count = data.loan_count || 0;
        } catch (error) {
            console.error('Error fetching dashboard data:', error);
            this.state.error = 'Failed to fetch data: ' + error.message;
        }
    }

    async fetchLoanDetails() {
        try {
            console.log('Fetching loan details...');
            const loans = await this.orm.searchRead('loan.details', [], [
                'loan_id',
                'member',
                'loan_product',
                'interest_rate',
                'disbursed_amount',
                'expected_outstanding',
                'actual_outstanding',
                'start_date',
            ]);
            console.log('Loan details:', loans);
            this.state.loanDetails = loans;
        } catch (error) {
            console.error('Error fetching loan details:', error);
            this.state.error = 'Failed to fetch loan details: ' + error.message;
        }
    }

    renderCharts() {
        if (this.barChartRef.el) {
            const barCtx = this.barChartRef.el.getContext('2d');
            if (this.state.barChart) this.state.barChart.destroy();
            this.state.barChart = new Chart(barCtx, {
                type: 'bar',
                data: {
                    labels: ['Expected Outstanding', 'Actual Outstanding'],
                    datasets: [{
                        label: 'Amount (UGX)',
                        data: [
                            this.state.expected_outstanding,
                            this.state.actual_outstanding,
                        ],
                        backgroundColor: ['#FF6384', '#36A2EB'],
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
    }

    downloadReport() {
        try {
            console.log('Triggering PDF report download...');
            this.orm.call('loan.portfolio', 'generate_pdf_report', []).then(action => {
                if (action) this.action.doAction(action);
            }).catch(error => {
                console.error('Download Error:', error);
            });
        } catch (error) {
            console.error('Download failed:', error);
        }
    }
}

LoanDashboardMain.template = 'my_hostel.LoanDashboardMainTemplate';

registry.category('actions').add('loan_dashboard_main', LoanDashboardMain);