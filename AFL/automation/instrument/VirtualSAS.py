import warnings

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr
import lazy_loader as lazy

from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import LabelEncoder

sasmodels = lazy.load("sasmodels", require="AFL-automation[sas-analysis]")


from AFL.automation.APIServer.Driver import Driver
from AFL.automation.shared.utilities import mpl_plot_to_bytes
AFLagent = lazy.load("AFL.agent", require="AFL-agent")

try:
    from AFL.agent.xarray_extensions import *
except ImportError:
    warnings.warn('AFL-agent xarray_extensions import failed! Some functionality may not work.  Install afl-agent',stacklevel=2)

class VirtualSAS(Driver):
    defaults = {}
    defaults['noise'] = 0.0
    defaults['ternary'] = False
    defaults['fast_locate'] = True

    # RFC hyperparameters
    defaults['rfc_n_estimators'] = 100
    defaults['rfc_max_depth'] = None
    defaults['rfc_random_state'] = 42
    defaults['rfc_min_samples_split'] = 2
    defaults['rfc_min_samples_leaf'] = 1

    # Boundary datasets structure
    defaults['boundary_datasets'] = {}

    # Components list
    defaults['components'] = []

    # Reference data configurations
    defaults['reference_data'] = []  # List of dicts with keys: q, I, dI, dq

    # SASView model configurations
    defaults['sasview_models'] = {}  # Dict: {label: {'model_name': str, 'model_kw': dict}}

    def __init__(self,overrides=None):
        '''
        Generates smoothly interpolated scattering data via a noiseless GPR from an experiments netcdf file.
        Uses RandomForestClassifier for phase boundary classification.
        '''
        self.app = None
        Driver.__init__(self,name='VirtualSAS_theory',defaults=self.gather_defaults(),overrides=overrides)

        import sasmodels.data
        import sasmodels.core
        import sasmodels.direct_model
        import sasmodels.bumps_model

        # Machine learning attributes for phase classification
        self.classifier = None
        self.label_encoder = LabelEncoder()
        self.X_train = None
        self.y_train = None
        self.phase_labels = None

        # Loaded reference data and models (created from config)
        self._reference_data = []
        self._sasmodels = {}

        # Keep boundary_dataset for backward compatibility
        self.boundary_dataset = None

        # Load reference data and models from config at startup
        self.load_reference_data()
        self.load_sasview_models()
        
    def status(self):
        status = []
        status.append(f'Configurations Loaded={len(self._reference_data)}')
        status.append(f'SASView Models={len(self._sasmodels)}')
        status.append(f'Components={self.config["components"]}')
        if self.classifier is not None:
            status.append(f'Classifier Trained=True')
            status.append(f'Phases={len(self.phase_labels)} {self.phase_labels}')
            status.append(f'Training Samples={len(self.X_train) if self.X_train is not None else 0}')
        else:
            status.append(f'Classifier Trained=False')
        status.append(f'Noise Level={self.config["noise"]}')
        status.append(f'Ternary={self.config["ternary"]}')
        if self.classifier is not None:
            status.append(f'RFC n_estimators={self.config["rfc_n_estimators"]}')
            status.append(f'RFC max_depth={self.config["rfc_max_depth"]}')
        return status

    def load_reference_data(self):
        '''
        Load reference data from config into sasmodels Data1D objects.

        Config format:
        reference_data = [
            {'q': [...], 'I': [...], 'dI': [...], 'dq': [...]},
            {'q': [...], 'I': [...], 'dI': [...], 'dq': [...]},
        ]
        '''
        import sasmodels.data

        self._reference_data = []

        for ref_config in self.config.get('reference_data', []):
            if not all(k in ref_config for k in ['q', 'I', 'dI', 'dq']):
                raise ValueError(
                    'Each reference_data entry must have keys: q, I, dI, dq. '
                    f'Got: {list(ref_config.keys())}'
                )

            data = sasmodels.data.Data1D(
                x=np.array(ref_config['q']),
                y=np.array(ref_config['I']),
                dy=np.array(ref_config['dI']),
                dx=np.array(ref_config['dq']),
            )
            self._reference_data.append(data)

    def load_sasview_models(self):
        '''
        Load SASView models from config.

        Config format:
        sasview_models = {
            'phase_A': {'model_name': 'sphere', 'model_kw': {'radius': 50, ...}},
            'phase_B': {'model_name': 'cylinder', 'model_kw': {'radius': 20, ...}},
        }
        '''
        import sasmodels.core
        import sasmodels.direct_model

        self._sasmodels = {}

        for label, model_config in self.config.get('sasview_models', {}).items():
            if 'model_name' not in model_config or 'model_kw' not in model_config:
                raise ValueError(
                    f'SASView model "{label}" must have "model_name" and "model_kw" keys'
                )

            calculators = []
            sasdatas = []
            for sasdata in self._reference_data:
                model_info = sasmodels.core.load_model_info(model_config['model_name'])
                kernel = sasmodels.core.build_model(model_info)
                calculator = sasmodels.direct_model.DirectModel(sasdata, kernel)
                calculators.append(calculator)
                sasdatas.append(sasdata)

            self._sasmodels[label] = {
                'name': model_config['model_name'],
                'kw': model_config['model_kw'],
                'calculators': calculators,
                'sasdata': sasdatas,
            }

    def validate_boundary_datasets_config(self):
        '''
        Validate boundary_datasets config structure and dimensionality.

        Returns
        -------
        bool
            True if valid, raises ValueError otherwise

        Raises
        ------
        ValueError
            If config structure is invalid
        '''
        boundary_datasets = self.config.get('boundary_datasets', {})

        if not isinstance(boundary_datasets, dict):
            raise ValueError('boundary_datasets must be a dictionary')

        if not boundary_datasets:
            raise ValueError('boundary_datasets is empty')

        for phase_label, phase_data in boundary_datasets.items():
            if not isinstance(phase_data, dict):
                raise ValueError(f'Phase "{phase_label}" data must be a dictionary')

            if 'points' not in phase_data:
                raise ValueError(f'Phase "{phase_label}" missing "points" key')

            points = np.array(phase_data['points'])
            if points.ndim != 2:
                raise ValueError(f'Phase "{phase_label}" points must be 2D array')

            # Validate ternary mode requirements
            if self.config['ternary']:
                # Ternary transformation requires exactly 3D input
                if points.shape[1] != 3:
                    raise ValueError(
                        f'Ternary mode enabled but phase "{phase_label}" has {points.shape[1]} '
                        f'dimensions. Ternary coordinate transformation requires 3D data.'
                    )

        return True

    def migrate_boundary_dataset_to_config(self):
        '''
        Convert old boundary_dataset xarray object to new config format.

        This is a migration helper for transitioning from the old shapely-based
        system to the new RFC-based system.

        Returns
        -------
        dict
            Boundary datasets in new config format

        Raises
        ------
        ValueError
            If boundary_dataset is None or invalid
        '''
        if self.boundary_dataset is None:
            raise ValueError('boundary_dataset is None, nothing to migrate')

        boundary_datasets = {}
        label_variable = self.boundary_dataset.attrs.get('labels')

        if label_variable is None:
            raise ValueError('boundary_dataset missing "labels" attribute')

        for label, sds in self.boundary_dataset.groupby(label_variable):
            # Extract components using same logic as old trace_boundaries
            comps = sds[sds.attrs['components']].transpose(..., 'component')
            points = comps.values.tolist()

            # Extract component names if available
            if 'components_dim' in sds.attrs:
                component_names = list(self.boundary_dataset[sds.attrs['components_dim']].values)
            else:
                component_names = list(sds.attrs.get('components', []))

            boundary_datasets[label] = {
                'points': points,
                'component_names': component_names
            }

        # Update config
        self.config['boundary_datasets'] = boundary_datasets

        return boundary_datasets

    def train_classifier(self, reset=True, drop_phases=None):
        '''
        Train RandomForestClassifier on boundary datasets from config.

        Parameters
        ----------
        reset : bool
            If True, reinitialize classifier before training
        drop_phases : list or None
            Phase labels to exclude from training

        Raises
        ------
        ValueError
            If boundary_datasets not configured or invalid format
        '''
        if drop_phases is None:
            drop_phases = []

        if reset:
            self.classifier = None
            self.X_train = None
            self.y_train = None

        # Validate config structure
        boundary_datasets = self.config.get('boundary_datasets', {})
        if not boundary_datasets:
            raise ValueError(
                'Must set boundary_datasets in config before training! '
                'Expected format: {"phase_A": {"points": [[x1,y1], [x2,y2], ...]}, ...}'
            )

        # Extract training data from config
        X_list = []
        y_list = []
        phase_labels = []

        for phase_label, phase_data in boundary_datasets.items():
            if phase_label in drop_phases:
                continue

            # Validate phase data structure
            if 'points' not in phase_data:
                raise ValueError(
                    f'Phase "{phase_label}" missing "points" key. '
                    f'Expected format: {{"points": [[x1,y1], [x2,y2], ...]}}'
                )

            points = np.array(phase_data['points'])

            # Validate dimensionality
            if points.ndim != 2:
                raise ValueError(
                    f'Phase "{phase_label}" points must be 2D array, got shape {points.shape}'
                )

            # Apply ternary coordinate transformation if enabled
            if self.config['ternary']:
                # Ternary transformation requires 3D input and produces 2D output
                if points.shape[1] != 3:
                    raise ValueError(
                        f'Ternary mode enabled but phase "{phase_label}" has {points.shape[1]} '
                        f'dimensions. Ternary coordinate transformation requires exactly 3D data.'
                    )
                # Convert ternary to xy for classifier
                xy = AFLagent.util.ternary_to_xy(points[:, [2, 0, 1]])  # Match old coordinate system
            else:
                # Use data as-is (can be any dimension: 2D, 3D, etc.)
                xy = points

            # Warn about insufficient samples
            if len(xy) < 3:
                warnings.warn(
                    f'Phase "{phase_label}" has only {len(xy)} training samples. '
                    f'RandomForestClassifier may not perform well. Recommend >= 10 samples per phase.',
                    stacklevel=2
                )

            X_list.append(xy)
            y_list.extend([phase_label] * len(xy))
            phase_labels.append(phase_label)

        if not X_list:
            raise ValueError('No training data available after filtering drop_phases')

        # Combine all training data
        self.X_train = np.vstack(X_list)
        self.y_train = np.array(y_list)
        self.phase_labels = phase_labels

        # Encode labels
        self.label_encoder.fit(self.y_train)
        y_encoded = self.label_encoder.transform(self.y_train)

        # Initialize and train RFC
        self.classifier = RandomForestClassifier(
            n_estimators=self.config['rfc_n_estimators'],
            max_depth=self.config['rfc_max_depth'],
            random_state=self.config['rfc_random_state'],
            min_samples_split=self.config['rfc_min_samples_split'],
            min_samples_leaf=self.config['rfc_min_samples_leaf'],
        )

        self.classifier.fit(self.X_train, y_encoded)


        # ds = xr.Dataset()
        # ds.attrs['classifier_trained'] = True
        # ds.attrs['n_training_samples'] = len(self.X_train)
        # ds.attrs['phase_labels'] = phase_labels
        # return ds
    
    def locate(self, composition):
        '''
        Predict phase membership using trained RandomForestClassifier.

        Parameters
        ----------
        composition : array-like
            Composition vector. Dimensionality depends on ternary mode:
            - ternary=True: Must be 3D (will be transformed to 2D for RFC)
            - ternary=False: Any dimension matching training data

        Returns
        -------
        ds : xr.Dataset
            Dataset containing:
            - 'phase': predicted phase label
            - 'probability': confidence score
            - attrs: all phase probabilities

        Notes
        -----
        Use locate_with_uncertainty() to get prediction probabilities as tuple
        '''
        composition = np.array(composition)

        if self.classifier is None:
            if (self.boundary_dataset is None) or (self._sasmodels is None):
                raise ValueError('Must call load_reference_data() and load_sasview_models() before locate()')
            else:
                self.train_classifier()

        # Convert to 2D array if needed (composition might be 1D)
        if composition.ndim == 1:
            composition = composition.reshape(1, -1)

        # Apply ternary coordinate transformation if enabled
        if self.config['ternary']:
            if composition.shape[1] != 3:
                raise ValueError(
                    f'Ternary mode enabled but composition has {composition.shape[1]} '
                    f'dimensions. Ternary transformation requires exactly 3D data.'
                )
            xy = AFLagent.util.ternary_to_xy(composition)
        else:
            # Use composition as-is (must match training data dimensionality)
            xy = composition

        # Validate dimensionality matches training data
        if xy.shape[1] != self.X_train.shape[1]:
            raise ValueError(
                f'Composition has {xy.shape[1]} dimensions after transformation, '
                f'but classifier was trained on {self.X_train.shape[1]}D data'
            )

        # Predict using RFC
        y_pred_encoded = self.classifier.predict(xy)
        y_pred = self.label_encoder.inverse_transform(y_pred_encoded)

        # Get probabilities for uncertainty
        y_proba = self.classifier.predict_proba(xy)
        max_proba = np.max(y_proba, axis=1)

        # Create xarray Dataset
        ds = xr.Dataset()
        ds['phase'] = str(y_pred[0])  # Convert to native Python string
        ds['probability'] = float(max_proba[0])

        # Store all probabilities in attrs (convert keys to native Python strings)
        ds.attrs['all_probabilities'] = {
            str(label): float(prob)
            for label, prob in zip(self.label_encoder.classes_, y_proba[0])
        }

        return ds

    def locate_with_uncertainty(self, composition):
        '''
        Predict phase with uncertainty estimation via predict_proba.

        Parameters
        ----------
        composition : array-like
            Composition vector. Dimensionality depends on ternary mode:
            - ternary=True: Must be 3D (will be transformed to 2D for RFC)
            - ternary=False: Any dimension matching training data

        Returns
        -------
        phase : str
            Predicted phase label
        probability : float
            Confidence score for predicted phase (0-1)
        all_probabilities : dict
            Probability scores for all phases {phase_label: probability}
        '''
        composition = np.array(composition)

        if self.classifier is None:
            raise ValueError('Must call train_classifier() before locate_with_uncertainty()')

        # Convert to 2D array if needed
        if composition.ndim == 1:
            composition = composition.reshape(1, -1)

        # Apply ternary coordinate transformation if enabled
        if self.config['ternary']:
            if composition.shape[1] != 3:
                raise ValueError(
                    f'Ternary mode enabled but composition has {composition.shape[1]} '
                    f'dimensions. Ternary transformation requires exactly 3D data.'
                )
            xy = AFLagent.util.ternary_to_xy(composition)
        else:
            # Use composition as-is
            xy = composition

        # Validate dimensionality matches training data
        if xy.shape[1] != self.X_train.shape[1]:
            raise ValueError(
                f'Composition has {xy.shape[1]} dimensions after transformation, '
                f'but classifier was trained on {self.X_train.shape[1]}D data'
            )

        # Predict class and probabilities
        y_pred_encoded = self.classifier.predict(xy)
        y_pred = self.label_encoder.inverse_transform(y_pred_encoded)
        y_proba = self.classifier.predict_proba(xy)

        phase = str(y_pred[0])  # Convert to native Python string
        probability = float(np.max(y_proba[0]))
        all_probabilities = {
            str(label): float(prob)  # Convert keys to native Python strings
            for label, prob in zip(self.label_encoder.classes_, y_proba[0])
        }

        # Create xarray Dataset
        ds = xr.Dataset()
        ds['phase'] = phase
        ds['probability'] = probability
        ds.attrs['all_probabilities'] = all_probabilities

        return ds

    def generate(self, label):
        '''
        Generate scattering data for a given phase label.

        Parameters
        ----------
        label : str
            Phase label (must exist in sasview_models config)

        Returns
        -------
        ds : xr.Dataset
            Dataset containing:
            - 'q': scattering vector
            - 'I': scattered intensity (with noise)
            - 'I_noiseless': scattered intensity (without noise)
            - 'dI': uncertainty
            - attrs: phase label, model name
        '''
        if label not in self._sasmodels:
            raise ValueError(
                f'Phase label "{label}" not found in sasview_models config. '
                f'Available: {list(self._sasmodels.keys())}'
            )

        kw = self._sasmodels[label]['kw']
        calculators = self._sasmodels[label]['calculators']
        sasdatas = self._sasmodels[label]['sasdata']
        noise = self.config['noise']

        q_list = []
        I_noiseless_list = []
        I_list = []
        dI_list = []

        for sasdata, calc in zip(sasdatas, calculators):
            I_noiseless = calc(**kw)

            dI_model = sasdata.dy * np.sqrt(I_noiseless / sasdata.y)
            mean_var = np.mean(dI_model * dI_model / I_noiseless)
            dI = sasdata.dy * noise / mean_var

            I = np.random.normal(loc=I_noiseless, scale=dI)

            q_list.append(sasdata.x)
            I_noiseless_list.append(I_noiseless)
            I_list.append(I)
            dI_list.append(dI)

        # Concatenate and sort by q
        q_all = np.concatenate(q_list)
        I_all = np.concatenate(I_list)
        I_noiseless_all = np.concatenate(I_noiseless_list)
        dI_all = np.concatenate(dI_list)

        # Sort by q
        sort_idx = np.argsort(q_all)
        q_sorted = q_all[sort_idx]
        I_sorted = I_all[sort_idx]
        I_noiseless_sorted = I_noiseless_all[sort_idx]
        dI_sorted = dI_all[sort_idx]

        # Create xarray Dataset
        ds = xr.Dataset(
            {
                'I': ('q', I_sorted),
                'I_noiseless': ('q', I_noiseless_sorted),
                'dI': ('q', dI_sorted),
            },
            coords={'q': q_sorted}
        )

        # Store metadata
        ds.attrs['phase'] = label
        ds.attrs['model_name'] = self._sasmodels[label]['name']

        return ds
    
    def expose(self, *args, **kwargs):
        '''
        Mimic the expose command from other instrument servers.

        Returns
        -------
        ds : xr.Dataset
            Combined dataset from locate() and generate() with composition info
        '''
        # Get components from config
        components = self.config.get('components', [])
        if not components:
            raise ValueError(
                'components not configured. Set config["components"] = [...] with component names'
            )

        # Validate all components are available in self.data
        if self.data is None:
            raise ValueError('self.data is None. Cannot extract sample_composition.')

        missing_components = []
        for component in components:
            if component not in self.data.get('sample_composition', {}):
                missing_components.append(component)

        if missing_components:
            raise ValueError(
                f'Components {missing_components} not found in self.data["sample_composition"]. '
                f'Available: {list(self.data.get("sample_composition", {}).keys())}'
            )

        # Extract composition from self.data
        composition = [self.data['sample_composition'][component]['value'] for component in components]

        # Get phase prediction from locate()
        ds_locate = self.locate(composition)
        label = str(ds_locate['phase'].item())  # Ensure native Python string

        # Generate scattering data
        ds_generate = self.generate(label)

        # Merge results
        ds = ds_generate.copy()

        # Add composition information
        ds['components'] = ('component', components)
        ds['composition'] = ('component', composition)

        # Merge locate results into attrs
        ds.attrs['phase'] = label
        ds.attrs['prediction_probability'] = ds_locate['probability'].item()
        ds.attrs['all_probabilities'] = ds_locate.attrs['all_probabilities']
        ds.attrs['components'] = components

        return ds
            
    @Driver.unqueued(render_hint='precomposed_svg')
    def plot_decision_boundaries(self, grid_resolution=200, **kwargs):
        '''
        Plot RFC decision boundaries with training data overlay.

        Parameters
        ----------
        grid_resolution : int
            Number of grid points per axis for decision boundary mesh
        '''
        matplotlib.use('Agg')  # very important
        fig, ax = plt.subplots(figsize=(10, 8))

        if self.classifier is None:
            plt.text(0.5, 0.5, 'No classifier trained. Run train_classifier()',
                     ha='center', va='center', fontsize=14)
            plt.xlim(0, 1)
            plt.ylim(0, 1)
        else:
            # Create mesh grid for decision boundary
            x_min, x_max = self.X_train[:, 0].min() - 0.05, self.X_train[:, 0].max() + 0.05
            y_min, y_max = self.X_train[:, 1].min() - 0.05, self.X_train[:, 1].max() + 0.05

            xx, yy = np.meshgrid(
                np.linspace(x_min, x_max, grid_resolution),
                np.linspace(y_min, y_max, grid_resolution)
            )

            # Predict on grid
            grid_points = np.c_[xx.ravel(), yy.ravel()]
            Z_encoded = self.classifier.predict(grid_points)
            Z_numeric = Z_encoded.reshape(xx.shape)

            # Plot decision boundary as contourf
            n_classes = len(self.label_encoder.classes_)
            contour = ax.contourf(xx, yy, Z_numeric, alpha=0.3, levels=n_classes - 1,
                                  cmap='viridis')

            # Overlay training data points
            y_train_encoded = self.label_encoder.transform(self.y_train)
            scatter = ax.scatter(
                self.X_train[:, 0],
                self.X_train[:, 1],
                c=y_train_encoded,
                cmap='viridis',
                edgecolors='black',
                s=50,
                alpha=0.8
            )

            # Add legend
            handles = []
            for i, label in enumerate(self.label_encoder.classes_):
                color_val = i / max(1, (n_classes - 1))
                handle = plt.Line2D([0], [0], marker='o', color='w',
                                  markerfacecolor=plt.cm.viridis(color_val),
                                  markersize=10, label=label, markeredgecolor='black')
                handles.append(handle)
            ax.legend(handles=handles, title='Phase', loc='best')

            ax.set_xlabel('X coordinate' if not self.config['ternary'] else 'Ternary X')
            ax.set_ylabel('Y coordinate' if not self.config['ternary'] else 'Ternary Y')
            ax.set_title(f'RFC Decision Boundaries (n={len(self.X_train)} samples)')

        svg = mpl_plot_to_bytes(fig, format='svg')
        plt.close(fig)
        return svg

    @Driver.unqueued(render_hint='precomposed_svg')
    def plot_hulls(self, **kwargs):
        '''
        DEPRECATED: Use plot_decision_boundaries() instead.
        This wrapper is provided for backward compatibility.
        '''
        warnings.warn(
            'plot_hulls() is deprecated and will be removed in future versions. '
            'Use plot_decision_boundaries() instead.',
            DeprecationWarning,
            stacklevel=2
        )
        return self.plot_decision_boundaries(**kwargs)

    @Driver.unqueued(render_hint='precomposed_svg')
    def plot_boundary_data(self, **kwargs):
        '''Plot boundary training data in ternary projection (if ternary mode enabled)'''
        matplotlib.use('Agg')  # very important

        if self.config['ternary']:
            fig, ax = plt.subplots(subplot_kw={'projection': 'ternary'})
        else:
            fig, ax = plt.subplots()

        if self.classifier is None:
            plt.text(0.5, 0.5, 'No classifier trained. Run train_classifier()',
                     ha='center', va='center')
            if not self.config['ternary']:
                plt.xlim(0, 1)
                plt.ylim(0, 1)
        else:
            # Plot training data from config
            boundary_datasets = self.config.get('boundary_datasets', {})

            for phase_label, phase_data in boundary_datasets.items():
                points = np.array(phase_data['points'])

                if self.config['ternary']:
                    # Plot in ternary space (assumes points are 3D ternary)
                    ax.scatter(points[:, 0], points[:, 1], points[:, 2],
                              label=phase_label, alpha=0.7, s=30)
                else:
                    # Plot in 2D
                    ax.scatter(points[:, 0], points[:, 1],
                              label=phase_label, alpha=0.7, s=30)

            ax.legend(title='Phase')
            ax.set_title('Boundary Training Data')

            if not self.config['ternary']:
                ax.set_xlabel('Component 1')
                ax.set_ylabel('Component 2')

        svg = mpl_plot_to_bytes(fig, format='svg')
        plt.close(fig)
        return svg
    
    

if __name__ == '__main__':
    from AFL.automation.shared.launcher import *
    # This allows the file to be run directly to start a server for this driver
    
