from django import forms

from myapp.models import ChangeResult

class ChangeResultForm(forms.ModelForm):
    class Meta:
        model = ChangeResult
        fields = ['uploaded_2023', 'uploaded_2025']

        widgets = {
            'uploaded_2023': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': '.tif,.tiff'
            }),
            'uploaded_2025': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': '.tif,.tiff'
            }),
        }


class SpatialJoinForm(forms.Form):
    main_shapefile = forms.FileField()
    change_shapefile = forms.FileField()