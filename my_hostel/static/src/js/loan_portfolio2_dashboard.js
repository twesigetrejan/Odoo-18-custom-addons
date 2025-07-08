/** @odoo-module **/

import { Component, onWillStart, onMounted, useState, useRef } from '@odoo/owl';
import { registry } from '@web/core/registry';
import { useService } from '@web/core/utils/hooks';
import { loadJS } from '@web/core/assets';

export class LoanPortfolio2Dashboard extends Component {
    setup() {
        super.setup();
        this.orm = useService('orm');
        this.action = useService('action');
        
        // Set default dates
        const today = new Date();
        const firstDayOfMonth = new Date(today.getFullYear(), today.getMonth(), 1);
        const lastDayOfMonth = new Date(today.getFullYear(), today.getMonth() + 1, 0);
        
        this.state = useState({
            dateFrom: firstDayOfMonth.toISOString().split('T')[0],
            dateTo: lastDayOfMonth.toISOString().split('T')[0],
            selectedBranch: '',
            selectedCurrency: '',
            compareEnabled: false,
            
            portfolioData: [],
            totals: {
                total_opening: 0,
                total_disbursements: 0,
                total_principal_repaid: 0,
                total_interest_earned: 0,
                total_closing: 0,
                total_change_percentage: 0
            },
            
            branches: [],
            currencies: [],
            error: null,
            loading: false
        });
        
        this.chartRef = useRef('portfolioChart');
        this.chart = null;

        onWillStart(async () => {
            await this.loadExternalLibraries();
            await this.loadFilterOptions();
            await this.loadDashboardData();
        });

        onMounted(() => {
            this.renderChart();
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
                this.state.error = `Failed to load required library: ${lib}`;
            }
        }
    }

    async loadFilterOptions() {
        try {
            const options = await this.orm.call('loan.portfolio2', 'get_filter_options', []);
            this.state.branches = options.branches || [];
            this.state.currencies = options.currencies || [];
            
            // Set default currency
            if (this.state.currencies.length > 0) {
                this.state.selectedCurrency = this.state.currencies[0].id;
            }
        } catch (error) {
            console.error('Failed to load filter options:', error);
            this.state.error = 'Failed to load filter options';
        }
    }

    async loadDashboardData() {
        this.state.loading = true;
        this.state.error = null;
        
        try {
            const params = {
                date_from: this.state.dateFrom,
                date_to: this.state.dateTo,
                branch_id: this.state.selectedBranch ? parseInt(this.state.selectedBranch) : null
            };

            const result = await this.orm.call('loan.portfolio2', 'get_dashboard_data', [], params);
            
            // Transform product_data object to array for template
            this.state.portfolioData = Object.entries(result.product_data || {}).map(([product, data]) => ({
                product: product,
                opening_portfolio: data.opening_portfolio || 0,
                disbursements: data.disbursements || 0,
                principal_repaid: data.principal_repaid || 0,
                interest_earned: data.interest_earned || 0,
                closing_portfolio: data.closing_portfolio || 0,
                change_percentage: data.change_percentage || 0
            }));
            
            // Calculate totals
            this.state.totals = {
                total_opening: result.total_opening || 0,
                total_disbursements: result.total_disbursements || 0,
                total_principal_repaid: result.total_principal_repaid || 0,
                total_interest_earned: result.total_interest_earned || 0,
                total_closing: result.total_closing || 0,
                total_change_percentage: this.calculateTotalChangePercentage(result.total_opening, result.total_closing)
            };
            
            // Update chart if it exists
            if (this.chart) {
                this.updateChart();
            }
            
        } catch (error) {
            console.error('Failed to load dashboard data:', error);
            this.state.error = 'Failed to load dashboard data';
        } finally {
            this.state.loading = false;
        }
    }

    calculateTotalChangePercentage(opening, closing) {
        if (opening && opening !== 0) {
            return ((closing - opening) / opening) * 100;
        }
        return 0;
    }

    // Event handlers
    async onDateFromChange(event) {
        this.state.dateFrom = event.target.value;
    }

    async onDateToChange(event) {
        this.state.dateTo = event.target.value;
    }

    async onBranchChange(event) {
        this.state.selectedBranch = event.target.value;
    }

    async onCurrencyChange(event) {
        this.state.selectedCurrency = event.target.value;
    }

    async onCompareChange(event) {
        this.state.compareEnabled = event.target.checked;
    }

    async applyFilters() {
        await this.loadDashboardData();
    }

    // Chart rendering
    renderChart() {
        if (!this.chartRef.el || !window.Chart) {
            return;
        }

        const ctx = this.chartRef.el.getContext('2d');
        
        // Destroy existing chart if it exists
        if (this.chart) {
            this.chart.destroy();
        }

        const labels = this.state.portfolioData.map(item => item.product);
        const openingData = this.state.portfolioData.map(item => item.opening_portfolio);
        const closingData = this.state.portfolioData.map(item => item.closing_portfolio);
        const disbursementsData = this.state.portfolioData.map(item => item.disbursements);

        this.chart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'Opening Portfolio',
                        data: openingData,
                        backgroundColor: 'rgba(54, 162, 235, 0.8)',
                        borderColor: 'rgba(54, 162, 235, 1)',
                        borderWidth: 1
                    },
                    {
                        label: 'Closing Portfolio',
                        data: closingData,
                        backgroundColor: 'rgba(75, 192, 192, 0.8)',
                        borderColor: 'rgba(75, 192, 192, 1)',
                        borderWidth: 1
                    },
                    {
                        label: 'Disbursements',
                        data: disbursementsData,
                        backgroundColor: 'rgba(255, 206, 86, 0.8)',
                        borderColor: 'rgba(255, 206, 86, 1)',
                        borderWidth: 1
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: 'Portfolio Performance by Product'
                    },
                    legend: {
                        display: true,
                        position: 'top'
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            callback: function(value) {
                                return this.formatCurrency(value);
                            }.bind(this)
                        }
                    }
                }
            }
        });
    }

    updateChart() {
        if (!this.chart) {
            this.renderChart();
            return;
        }

        const labels = this.state.portfolioData.map(item => item.product);
        const openingData = this.state.portfolioData.map(item => item.opening_portfolio);
        const closingData = this.state.portfolioData.map(item => item.closing_portfolio);
        const disbursementsData = this.state.portfolioData.map(item => item.disbursements);

        this.chart.data.labels = labels;
        this.chart.data.datasets[0].data = openingData;
        this.chart.data.datasets[1].data = closingData;
        this.chart.data.datasets[2].data = disbursementsData;
        
        this.chart.update();
    }

    // Utility methods
    formatCurrency(amount) {
        const currency = this.state.currencies.find(c => c.id === parseInt(this.state.selectedCurrency));
        const symbol = currency ? currency.symbol : '$';
        
        return new Intl.NumberFormat('en-US', {
            style: 'currency',
            currency: 'USD',
            minimumFractionDigits: 0,
            maximumFractionDigits: 0
        }).format(amount).replace('$', symbol);
    }

    // Action methods
    async exportData() {
        try {
            const data = {
                portfolioData: this.state.portfolioData,
                totals: this.state.totals,
                filters: {
                    dateFrom: this.state.dateFrom,
                    dateTo: this.state.dateTo,
                    selectedBranch: this.state.selectedBranch,
                    selectedCurrency: this.state.selectedCurrency
                }
            };

            // Convert to CSV
            const csvContent = this.convertToCSV(data);
            
            // Create and download file
            const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
            const link = document.createElement('a');
            const url = URL.createObjectURL(blob);
            link.setAttribute('href', url);
            link.setAttribute('download', `loan_portfolio_${this.state.dateFrom}_to_${this.state.dateTo}.csv`);
            link.style.visibility = 'hidden';
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            
        } catch (error) {
            console.error('Export failed:', error);
            this.state.error = 'Export failed';
        }
    }

    convertToCSV(data) {
        const headers = ['Product', 'Opening Portfolio', 'Disbursements', 'Principal Repaid', 'Interest Earned', 'Closing Portfolio', 'Change %'];
        const csvRows = [headers.join(',')];
        
        // Add data rows
        data.portfolioData.forEach(item => {
            const row = [
                item.product,
                item.opening_portfolio,
                item.disbursements,
                item.principal_repaid,
                item.interest_earned,
                item.closing_portfolio,
                item.change_percentage.toFixed(2)
            ];
            csvRows.push(row.join(','));
        });
        
        // Add totals row
        const totalsRow = [
            'TOTALS',
            data.totals.total_opening,
            data.totals.total_disbursements,
            data.totals.total_principal_repaid,
            data.totals.total_interest_earned,
            data.totals.total_closing,
            data.totals.total_change_percentage.toFixed(2)
        ];
        csvRows.push(totalsRow.join(','));
        
        return csvRows.join('\n');
    }

    async downloadReport() {
        try {
            const params = {
                date_from: this.state.dateFrom,
                date_to: this.state.dateTo,
                branch_id: this.state.selectedBranch ? parseInt(this.state.selectedBranch) : null
            };

            const result = await this.orm.call('loan.portfolio2', 'generate_snapshot_report', [], params);
            
            if (result && result.type === 'ir.actions.report') {
                this.action.doAction(result);
            }
            
        } catch (error) {
            console.error('Report generation failed:', error);
            this.state.error = 'Report generation failed';
        }
    }

}
LoanPortfolio2Dashboard.template = 'my_hostel.LoanPortfolio2DashboardTemplate';

registry.category('actions').add('loan_portfolio2_dashboard', LoanPortfolio2Dashboard);