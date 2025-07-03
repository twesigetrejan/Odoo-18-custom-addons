/** @odoo-module **/

import { Component, onWillStart, onMounted, useState, useRef } from '@odoo/owl';
import { registry } from '@web/core/registry';
import { useService } from '@web/core/utils/hooks';
import { loadJS } from '@web/core/assets';

export class SavingsDashboardMain extends Component {
    setup() {
        super.setup();
        this.orm = useService('orm');
        this.action = useService('action');
        this.state = useState({
            total_accounts: 0,
            total_balances: 0,
            dormant_accounts: 0,
            dormant_balances: 0,
            dormant_percentage: 0,
            low_balance_accounts: 0,
            error: null,
            accountDetails: [],

            // Filter options
            members: [],
            productTypes: [],
            portfolios: [],
            
            // Filter values
            selectedMember: '',
            selectedProduct: '',
            selectedPortfolio: '',
            dormancyPeriod: 90,
            balanceThreshold: 50000,
            
            isFiltered: false,
        });
        
        this.barChartRef = useRef('barChart');
        this.pieChartRef = useRef('pieChart');
        this.idleChartRef = useRef('idleChart');

        onWillStart(async () => {
            await this.loadExternalLibraries();
            await this.fetchFilterOptions();
            await this.fetchDashboardData();
        });

        onMounted(() => {
            this.renderCharts();
        });
    }

    async loadExternalLibraries() {
        const libraries = [
            'https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js',
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

    async fetchFilterOptions() {
        try {
            const options = await this.orm.call('saving.portfolio', 'get_filter_options', []);
            this.state.members = options.members || [];
            this.state.productTypes = options.product_types || [];
            this.state.portfolios = options.portfolios || [];
        } catch (error) {
            console.error('Error fetching filter options:', error);
            this.state.error = 'Failed to fetch filter options: ' + error.message;
        }
    }

    async fetchDashboardData() {
        try {
            const hasFilters = this.state.selectedMember || this.state.selectedProduct || this.state.selectedPortfolio;
            
            if (hasFilters) {
                const data = await this.orm.call('saving.portfolio', 'get_filtered_metrics', [
                    this.state.selectedMember || null,
                    this.state.selectedProduct || null,
                    this.state.selectedPortfolio || null,
                    this.state.dormancyPeriod,
                    this.state.balanceThreshold
                ]);
                this.updateStateFromData(data);
                this.state.isFiltered = true;
            } else {
                const data = await this.orm.call('saving.portfolio', 'get_overview_metrics', [
                    this.state.dormancyPeriod,
                    this.state.balanceThreshold
                ]);
                this.updateStateFromData(data);
                this.state.isFiltered = false;
                
                await this.fetchAccountDetails();
            }
        } catch (error) {
            console.error('Error fetching dashboard data:', error);
            this.state.error = 'Failed to fetch data: ' + error.message;
        }
    }

    updateStateFromData(data) {
        this.state.total_accounts = data.total_accounts || 0;
        this.state.total_balances = data.total_balances || 0;
        this.state.dormant_accounts = data.dormant_accounts || 0;
        this.state.dormant_balances = data.dormant_balances || 0;
        this.state.dormant_percentage = data.dormant_percentage || 0;
        this.state.low_balance_accounts = data.low_balance_accounts || 0;
        this.state.accountDetails = data.account_details || [];
    }

    async fetchAccountDetails() {
        try {
            const accounts = await this.orm.searchRead('saving.details', [], [
                'member_id',
                'member_name',
                'product_type',
                'portfolio_id',
                'balance',
                'days_idle',
                'last_transaction_date',
            ]);
            
            this.state.accountDetails = accounts.map(acc => ({
                id: acc.id,
                member_id: acc.member_id,
                member_name: acc.member_name,
                product_type: acc.product_type,
                portfolio: acc.portfolio_id ? acc.portfolio_id[1] : '',
                balance: acc.balance,
                days_idle: acc.days_idle,
                last_transaction_date: acc.last_transaction_date || '',
                is_dormant: acc.days_idle >= this.state.dormancyPeriod,
                is_low_balance: acc.balance < this.state.balanceThreshold
            }));
        } catch (error) {
            console.error('Error fetching account details:', error);
            this.state.error = 'Failed to fetch account details: ' + error.message;
        }
    }

    async onMemberFilterChange(event) {
        this.state.selectedMember = event.target.value;
        await this.fetchDashboardData();
        this.renderCharts();
    }

    async onProductFilterChange(event) {
        this.state.selectedProduct = event.target.value;
        await this.fetchDashboardData();
        this.renderCharts();
    }

    async onPortfolioFilterChange(event) {
        this.state.selectedPortfolio = event.target.value;
        await this.fetchDashboardData();
        this.renderCharts();
    }

    async onDormancyPeriodChange(event) {
        this.state.dormancyPeriod = parseInt(event.target.value) || 90;
        await this.fetchDashboardData();
        this.renderCharts();
    }

    async onBalanceThresholdChange(event) {
        this.state.balanceThreshold = parseInt(event.target.value) || 50000;
        await this.fetchDashboardData();
        this.renderCharts();
    }

    async clearFilters() {
        this.state.selectedMember = '';
        this.state.selectedProduct = '';
        this.state.selectedPortfolio = '';
        this.state.dormancyPeriod = 90;
        this.state.balanceThreshold = 50000;
        await this.fetchDashboardData();
        this.renderCharts();
    }

    renderCharts() {
        this.renderBarChart();
        this.renderPieChart();
        this.renderIdleChart();
    }

    renderBarChart() {
        if (this.barChartRef.el) {
            const ctx = this.barChartRef.el.getContext('2d');
            if (this.state.barChart) this.state.barChart.destroy();
            
            this.state.barChart = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: ['Total Accounts', 'Dormant Accounts', 'Low Balance Accounts'],
                    datasets: [{
                        label: 'Count',
                        data: [
                            this.state.total_accounts,
                            this.state.dormant_accounts,
                            this.state.low_balance_accounts,
                        ],
                        backgroundColor: ['#36A2EB', '#FF6384', '#FFCE56'],
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: { y: { beginAtZero: true } },
                    plugins: { legend: { display: false } },
                },
            });
        }
    }

    renderPieChart() {
        if (this.pieChartRef.el) {
            const ctx = this.pieChartRef.el.getContext('2d');
            if (this.state.pieChart) this.state.pieChart.destroy();
            
            const activeAccounts = this.state.total_accounts - this.state.dormant_accounts;
            
            this.state.pieChart = new Chart(ctx, {
                type: 'pie',
                data: {
                    labels: ['Active Accounts', 'Dormant Accounts'],
                    datasets: [{
                        data: [activeAccounts, this.state.dormant_accounts],
                        backgroundColor: ['#36A2EB', '#FF6384'],
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { position: 'bottom' } },
                },
            });
        }
    }

    async renderIdleChart() {
        try {
            const distribution = await this.orm.call('saving.portfolio', 'get_idle_distribution', []);
            
            if (this.idleChartRef.el) {
                const ctx = this.idleChartRef.el.getContext('2d');
                if (this.state.idleChart) this.state.idleChart.destroy();
                
                this.state.idleChart = new Chart(ctx, {
                    type: 'bar',
                    data: {
                        labels: ['30+ Days', '60+ Days', '120+ Days', '160+ Days'],
                        datasets: [{
                            label: 'Count by Days Idle',
                            data: [
                                distribution['30'],
                                distribution['60'],
                                distribution['120'],
                                distribution['160+'],
                            ],
                            backgroundColor: ['#4BC0C0', '#9966FF', '#FF9F40', '#FF6384'],
                        }],
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        scales: { y: { beginAtZero: true } },
                        plugins: { legend: { display: false } },
                    },
                });
            }
        } catch (error) {
            console.error('Error rendering idle chart:', error);
        }
    }

    downloadReport() {
        try {
            const memberFilter = this.state.selectedMember || null;
            const productFilter = this.state.selectedProduct || null;
            const portfolioFilter = this.state.selectedPortfolio || null;
            
            this.orm.call('saving.portfolio', 'generate_pdf_report', [
                memberFilter,
                productFilter,
                portfolioFilter,
                this.state.dormancyPeriod,
                this.state.balanceThreshold
            ]).then(action => {
                if (action) {
                    this.action.doAction(action);
                }
            }).catch(error => {
                console.error('Download Error:', error);
                this.state.error = 'Failed to generate PDF report: ' + error.message;
            });
        } catch (error) {
            console.error('Download failed:', error);
            this.state.error = 'Failed to download report: ' + error.message;
        }
    }

    getProductTypeDisplay(value) {
        const productTypes = {
            'ordinary': 'Ordinary Savings',
            'fixed_deposit': 'Fixed Deposit',
            'premium': 'Premium Savings',
            'regular': 'Regular Savings',
            'youth': 'Youth Savings',
        };
        return productTypes[value] || value;
    }

    formatCurrency(amount) {
        return new Intl.NumberFormat('en-UG', {
            style: 'currency',
            currency: 'UGX',
            minimumFractionDigits: 0,
            maximumFractionDigits: 0,
        }).format(amount);
    }

    formatDate(dateString) {
        if (!dateString) return '';
        return new Date(dateString).toLocaleDateString('en-UG');
    }
}

SavingsDashboardMain.template = 'my_hostel.SavingsDashboardMainTemplate';

registry.category('actions').add('savings_dashboard_main', SavingsDashboardMain);